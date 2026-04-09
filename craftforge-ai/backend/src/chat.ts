/**
 * Claude conversation handler with tool use for product search.
 */

import { SYSTEM_PROMPT, TOOLS, FAQ_PATTERNS } from "./prompts";
import {
  searchProducts,
  getProductDetails,
  getComplementaryProducts,
  type ProductResult,
} from "./search";

interface Env {
  PRODUCTS: VectorizeIndex;
  ANTHROPIC_API_KEY: string;
  VOYAGE_API_KEY: string;
  SHOPIFY_TOKEN: string;
  SHOPIFY_STORE: string;
  MAX_MESSAGES_PER_SESSION: string;
}

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

interface ChatRequest {
  message: string;
  history: ChatMessage[];
  sessionId: string;
  context?: {
    currentPage?: string;
    cartTotal?: number;
    preferences?: Record<string, string>;
  };
}

function checkFAQ(message: string): string | null {
  for (const faq of FAQ_PATTERNS) {
    if (faq.pattern.test(message)) return faq.answer;
  }
  return null;
}

function formatProductsForClaude(products: ProductResult[]): string {
  if (!products.length) return "No products found matching that criteria.";

  return products
    .map(
      (p) =>
        `<product handle="${p.handle}" title="${p.title}" price="${p.price.toFixed(2)}" ` +
        `${p.compare_at_price ? `compare_at="${p.compare_at_price.toFixed(2)}" ` : ""}` +
        `image="${p.image}" scale="${p.scale}" theme="${p.theme}" ` +
        `difficulty="${p.difficulty}" in_stock="${p.in_stock}" />`,
    )
    .join("\n");
}

async function executeTool(
  toolName: string,
  toolInput: Record<string, unknown>,
  env: Env,
): Promise<{ result: string; sideEffect?: Record<string, unknown> }> {
  console.log(`[chat] executeTool: ${toolName}`, JSON.stringify(toolInput));

  try {
    switch (toolName) {
      case "search_products": {
        const products = await searchProducts(
          String(toolInput.query),
          {
            scale: toolInput.scale as string | undefined,
            theme: toolInput.theme as string | undefined,
            price_max: toolInput.price_max as number | undefined,
            difficulty: toolInput.difficulty as number | undefined,
          },
          env,
        );
        console.log(`[chat] search returned ${products.length} products`);
        return { result: formatProductsForClaude(products) };
      }

      case "get_product_details": {
        const product = await getProductDetails(String(toolInput.handle), env);
        if (!product) return { result: "Product not found." };
        return { result: JSON.stringify(product) };
      }

      case "get_complementary_products": {
        const products = await getComplementaryProducts(
          String(toolInput.product_handle),
          String(toolInput.complement_type),
          env,
        );
        return { result: formatProductsForClaude(products) };
      }

      case "add_to_cart": {
        return {
          result: `Product "${toolInput.handle}" queued for cart (quantity: ${toolInput.quantity || 1}). The frontend will execute the cart add.`,
          sideEffect: {
            action: "add_to_cart",
            handle: toolInput.handle,
            quantity: toolInput.quantity || 1,
          },
        };
      }

      case "apply_discount": {
        return {
          result: `Discount code "${toolInput.code}" will be applied at checkout.`,
          sideEffect: {
            action: "apply_discount",
            code: toolInput.code,
          },
        };
      }

      default:
        return { result: `Unknown tool: ${toolName}` };
    }
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    console.error(`[chat] executeTool ${toolName} FAILED:`, msg);
    return { result: `Tool error: ${msg}` };
  }
}

/**
 * Pick the right Claude model ID.
 * Sonnet for initial messages (richer reasoning), Haiku for follow-ups (faster/cheaper).
 */
function pickModel(historyLength: number): string {
  // Use the correct model IDs from Anthropic's API
  if (historyLength < 6) {
    return "claude-sonnet-4-5-20241022";
  }
  return "claude-haiku-4-5-20251001";
}

/**
 * Main chat handler.
 */
export async function handleChat(
  request: ChatRequest,
  env: Env,
): Promise<Response> {
  console.log(`[chat] handleChat called. message="${request.message.substring(0, 80)}" history=${request.history.length}`);

  try {
    const maxMessages = parseInt(env.MAX_MESSAGES_PER_SESSION) || 20;

    // Rate limit check
    if (request.history.length >= maxMessages * 2) {
      console.log("[chat] Rate limited — session too long");
      return new Response(
        JSON.stringify({
          type: "error",
          message: "Session limit reached. Please start a new conversation.",
        }),
        { status: 429, headers: { "Content-Type": "application/json" } },
      );
    }

    // Basic profanity filter
    const abusivePattern = /\b(fuck|shit|ass|bitch|dick|cunt)\b/i;
    const cleanMessage = abusivePattern.test(request.message)
      ? request.message.replace(abusivePattern, "***")
      : request.message;

    // Check FAQ for instant response
    const faqAnswer = checkFAQ(cleanMessage);
    if (faqAnswer && request.history.length < 4) {
      console.log("[chat] FAQ match — returning cached answer");
      return new Response(
        JSON.stringify({ type: "message", content: faqAnswer, actions: [] }),
        { headers: { "Content-Type": "application/json" } },
      );
    }

    // Build context enhancement
    let contextNote = "";
    if (request.context?.cartTotal) {
      const total = request.context.cartTotal / 100;
      if (total > 0 && total < 50) {
        contextNote = `\n[Context: User has $${total.toFixed(2)} in cart. They're $${(50 - total).toFixed(2)} from the free sticker pack threshold.]`;
      }
    }
    if (request.context?.currentPage) {
      contextNote += `\n[Context: User is currently on ${request.context.currentPage}]`;
    }

    // Build messages array for Claude
    const messages: Array<{ role: string; content: unknown }> = [];
    for (const msg of request.history) {
      messages.push({ role: msg.role, content: msg.content });
    }
    messages.push({ role: "user", content: cleanMessage + contextNote });

    // Call Claude with tool use — loop until we get a final text response
    const actions: Array<Record<string, unknown>> = [];
    let finalContent = "";
    let iterations = 0;
    const maxIterations = 5;
    let currentMessages = [...messages];

    while (iterations < maxIterations) {
      iterations++;

      const model = pickModel(request.history.length);
      console.log(`[chat] Iteration ${iterations}: calling Claude model=${model} messages=${currentMessages.length}`);

      // Validate API key format
      if (!env.ANTHROPIC_API_KEY || !env.ANTHROPIC_API_KEY.startsWith("sk-ant-")) {
        console.error("[chat] ANTHROPIC_API_KEY missing or wrong format. Got:", env.ANTHROPIC_API_KEY ? env.ANTHROPIC_API_KEY.substring(0, 10) + "..." : "EMPTY");
        return new Response(
          JSON.stringify({ type: "error", message: "AI service misconfigured. Please contact support." }),
          { status: 500, headers: { "Content-Type": "application/json" } },
        );
      }

      const claudeBody = {
        model,
        max_tokens: 1024,
        system: SYSTEM_PROMPT,
        tools: TOOLS,
        messages: currentMessages,
      };

      console.log("[chat] Claude request body size:", JSON.stringify(claudeBody).length, "bytes");

      let claudeResp: Response;
      try {
        claudeResp = await fetch("https://api.anthropic.com/v1/messages", {
          method: "POST",
          headers: {
            "x-api-key": env.ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
          },
          body: JSON.stringify(claudeBody),
        });
      } catch (fetchErr) {
        const msg = fetchErr instanceof Error ? fetchErr.message : String(fetchErr);
        console.error("[chat] Claude fetch() threw:", msg);
        return new Response(
          JSON.stringify({ type: "error", message: "Failed to reach AI service: " + msg }),
          { status: 502, headers: { "Content-Type": "application/json" } },
        );
      }

      console.log(`[chat] Claude response: status=${claudeResp.status}`);

      if (!claudeResp.ok) {
        let errBody = "";
        try { errBody = await claudeResp.text(); } catch { errBody = "(could not read body)"; }
        console.error(`[chat] Claude API error ${claudeResp.status}:`, errBody.substring(0, 500));
        return new Response(
          JSON.stringify({
            type: "error",
            message: `AI error (${claudeResp.status}). Details: ${errBody.substring(0, 200)}`,
          }),
          { status: 502, headers: { "Content-Type": "application/json" } },
        );
      }

      let claudeData: {
        content: Array<{
          type: string;
          text?: string;
          id?: string;
          name?: string;
          input?: Record<string, unknown>;
        }>;
        stop_reason: string;
      };

      try {
        claudeData = await claudeResp.json() as typeof claudeData;
      } catch (parseErr) {
        const msg = parseErr instanceof Error ? parseErr.message : String(parseErr);
        console.error("[chat] Failed to parse Claude response JSON:", msg);
        return new Response(
          JSON.stringify({ type: "error", message: "Failed to parse AI response" }),
          { status: 502, headers: { "Content-Type": "application/json" } },
        );
      }

      console.log(`[chat] Claude stop_reason=${claudeData.stop_reason} content_blocks=${claudeData.content?.length}`);

      if (claudeData.stop_reason === "tool_use") {
        const assistantContent: unknown[] = [];
        const toolResults: unknown[] = [];

        for (const block of claudeData.content) {
          if (block.type === "text" && block.text) {
            assistantContent.push({ type: "text", text: block.text });
            finalContent += block.text;
          } else if (block.type === "tool_use" && block.name && block.input) {
            console.log(`[chat] Tool call: ${block.name} id=${block.id}`);
            assistantContent.push({
              type: "tool_use",
              id: block.id,
              name: block.name,
              input: block.input,
            });

            const { result, sideEffect } = await executeTool(block.name, block.input, env);
            if (sideEffect) actions.push(sideEffect);

            toolResults.push({
              type: "tool_result",
              tool_use_id: block.id,
              content: result,
            });
            console.log(`[chat] Tool result for ${block.name}: ${result.substring(0, 100)}...`);
          }
        }

        currentMessages.push({ role: "assistant", content: assistantContent });
        currentMessages.push({ role: "user", content: toolResults });
      } else {
        for (const block of claudeData.content) {
          if (block.type === "text" && block.text) {
            finalContent += block.text;
          }
        }
        console.log(`[chat] Final response: ${finalContent.length} chars`);
        break;
      }
    }

    console.log(`[chat] Returning response. content=${finalContent.length} chars, actions=${actions.length}`);

    return new Response(
      JSON.stringify({ type: "message", content: finalContent, actions }),
      { headers: { "Content-Type": "application/json", "Cache-Control": "no-cache" } },
    );
  } catch (err) {
    const msg = err instanceof Error ? `${err.message}\n${err.stack}` : String(err);
    console.error("[chat] UNCAUGHT ERROR in handleChat:", msg);
    return new Response(
      JSON.stringify({ type: "error", message: "Internal error: " + (err instanceof Error ? err.message : String(err)) }),
      { status: 500, headers: { "Content-Type": "application/json" } },
    );
  }
}
