/**
 * Claude conversation handler with tool use for product search.
 * Streams responses via SSE.
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

/**
 * Check if message matches an FAQ pattern for instant response.
 */
function checkFAQ(message: string): string | null {
  for (const faq of FAQ_PATTERNS) {
    if (faq.pattern.test(message)) return faq.answer;
  }
  return null;
}

/**
 * Format product results as structured data for Claude + frontend.
 */
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

/**
 * Execute a tool call from Claude.
 */
async function executeTool(
  toolName: string,
  toolInput: Record<string, unknown>,
  env: Env,
): Promise<{ result: string; sideEffect?: Record<string, unknown> }> {
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
      // The actual cart add happens on the frontend — we return the instruction
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
}

/**
 * Main chat handler — streams SSE response.
 */
export async function handleChat(
  request: ChatRequest,
  env: Env,
): Promise<Response> {
  const maxMessages = parseInt(env.MAX_MESSAGES_PER_SESSION) || 20;

  // Rate limit check
  if (request.history.length >= maxMessages * 2) {
    return new Response(
      JSON.stringify({
        type: "error",
        message: "Session limit reached. Please start a new conversation.",
      }),
      { status: 429, headers: { "Content-Type": "application/json" } },
    );
  }

  // Basic profanity/abuse filter
  const abusivePattern = /\b(fuck|shit|ass|bitch|dick|cunt)\b/i;
  const cleanMessage = abusivePattern.test(request.message)
    ? request.message.replace(abusivePattern, "***")
    : request.message;

  // Check FAQ for instant response
  const faqAnswer = checkFAQ(cleanMessage);
  if (faqAnswer && request.history.length < 4) {
    // Only use FAQ shortcut early in conversation
    return new Response(
      JSON.stringify({
        type: "message",
        content: faqAnswer,
        actions: [],
      }),
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

    const claudeResp = await fetch("https://api.anthropic.com/v1/messages", {
      method: "POST",
      headers: {
        "x-api-key": env.ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
      },
      body: JSON.stringify({
        model:
          request.history.length < 6
            ? "claude-sonnet-4-6-20250514"
            : "claude-haiku-4-5-20251001",
        max_tokens: 1024,
        system: SYSTEM_PROMPT,
        tools: TOOLS,
        messages: currentMessages,
      }),
    });

    if (!claudeResp.ok) {
      const err = await claudeResp.text();
      return new Response(
        JSON.stringify({ type: "error", message: `Claude API error: ${claudeResp.status}` }),
        { status: 502, headers: { "Content-Type": "application/json" } },
      );
    }

    const claudeData = (await claudeResp.json()) as {
      content: Array<{
        type: string;
        text?: string;
        id?: string;
        name?: string;
        input?: Record<string, unknown>;
      }>;
      stop_reason: string;
    };

    // Check if Claude wants to use tools
    if (claudeData.stop_reason === "tool_use") {
      // Collect all text + tool use blocks
      const assistantContent: unknown[] = [];
      const toolResults: unknown[] = [];

      for (const block of claudeData.content) {
        if (block.type === "text" && block.text) {
          assistantContent.push({ type: "text", text: block.text });
          finalContent += block.text;
        } else if (block.type === "tool_use" && block.name && block.input) {
          assistantContent.push({
            type: "tool_use",
            id: block.id,
            name: block.name,
            input: block.input,
          });

          // Execute the tool
          const { result, sideEffect } = await executeTool(
            block.name,
            block.input,
            env,
          );
          if (sideEffect) actions.push(sideEffect);

          toolResults.push({
            type: "tool_result",
            tool_use_id: block.id,
            content: result,
          });
        }
      }

      // Add assistant message with tool calls + tool results
      currentMessages.push({ role: "assistant", content: assistantContent });
      currentMessages.push({ role: "user", content: toolResults });
    } else {
      // Final response — extract text
      for (const block of claudeData.content) {
        if (block.type === "text" && block.text) {
          finalContent += block.text;
        }
      }
      break;
    }
  }

  return new Response(
    JSON.stringify({
      type: "message",
      content: finalContent,
      actions,
    }),
    {
      headers: {
        "Content-Type": "application/json",
        "Cache-Control": "no-cache",
      },
    },
  );
}
