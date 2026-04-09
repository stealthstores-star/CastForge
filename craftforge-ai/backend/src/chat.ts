import { SYSTEM_PROMPT, TOOLS, FAQ_PATTERNS } from "./prompts";
import {
  searchProducts,
  getProductDetails,
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
  if (!products.length) {
    return '{"count":0,"note":"No products found. Use the zero-results script."}';
  }
  return JSON.stringify({
    count: products.length,
    note: "Cards render automatically. Write only the 1-2 sentence reply per the response shape rules. Do not list titles or prices.",
    items: products.map((p) => ({
      title: p.title,
      scale: p.scale,
      price: p.price,
    })),
  });
}

interface ToolOutcome {
  result: string;
  sideEffect?: Record<string, unknown>;
  products?: ProductResult[];
}

async function executeTool(
  toolName: string,
  toolInput: Record<string, unknown>,
  env: Env,
): Promise<ToolOutcome> {
  console.log(`[chat] executeTool: ${toolName}`, JSON.stringify(toolInput));
  try {
    switch (toolName) {
      case "search_products": {
        const products = await searchProducts(
          String(toolInput.query),
          {
            scale: toolInput.scale as string | undefined,
            price_max: toolInput.price_max as number | undefined,
          },
          env,
        );
        console.log(`[chat] search returned ${products.length} products`);
        return { result: formatProductsForClaude(products), products };
      }
      case "get_product_details": {
        const product = await getProductDetails(String(toolInput.handle), env);
        if (!product) return { result: "Product not found." };
        return { result: JSON.stringify(product) };
      }
      case "add_to_cart": {
        return {
          result: `Queued add_to_cart for "${toolInput.handle}" qty ${toolInput.quantity || 1}.`,
          sideEffect: {
            action: "add_to_cart",
            handle: toolInput.handle,
            quantity: toolInput.quantity || 1,
          },
        };
      }
      default:
        return { result: `Unknown tool: ${toolName}` };
    }
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    console.error(`[chat] executeTool ${toolName} FAILED:`, msg);
    return { result: '{"error": "search_unavailable"}' };
  }
}

function pickModel(historyLength: number): string {
  return historyLength < 6 ? "claude-sonnet-4-5" : "claude-haiku-4-5";
}

export async function handleChat(
  request: ChatRequest,
  env: Env,
): Promise<Response> {
  console.log(`[chat] handleChat called. message="${request.message.substring(0, 80)}" history=${request.history.length}`);

  try {
    const maxMessages = parseInt(env.MAX_MESSAGES_PER_SESSION) || 20;

    if (request.history.length >= maxMessages * 2) {
      return new Response(
        JSON.stringify({ type: "error", message: "Session limit reached. Please start a new conversation." }),
        { status: 429, headers: { "Content-Type": "application/json" } },
      );
    }

    const abusivePattern = /\b(fuck|shit|ass|bitch|dick|cunt)\b/i;
    const cleanMessage = abusivePattern.test(request.message)
      ? request.message.replace(abusivePattern, "***")
      : request.message;

    const faqAnswer = checkFAQ(cleanMessage);
    if (faqAnswer && request.history.length < 4) {
      console.log("[chat] FAQ match");
      return new Response(
        JSON.stringify({ type: "message", content: faqAnswer, products: [], actions: [] }),
        { headers: { "Content-Type": "application/json" } },
      );
    }

    let contextNote = "";
    if (request.context?.cartTotal) {
      const total = request.context.cartTotal / 100;
      if (total > 0 && total < 50) {
        contextNote = `\n[Context: User has $${total.toFixed(2)} in cart.]`;
      }
    }
    if (request.context?.currentPage) {
      contextNote += `\n[Context: User is on ${request.context.currentPage}]`;
    }

    const messages: Array<{ role: string; content: unknown }> = [];
    for (const msg of request.history) {
      messages.push({ role: msg.role, content: msg.content });
    }
    messages.push({ role: "user", content: cleanMessage + contextNote });

    const actions: Array<Record<string, unknown>> = [];
    const collectedProducts: ProductResult[] = [];
    let finalContent = "";
    let iterations = 0;
    const maxIterations = 4;
    let currentMessages = [...messages];

    while (iterations < maxIterations) {
      iterations++;
      const model = pickModel(request.history.length);
      console.log(`[chat] Iteration ${iterations}: model=${model} messages=${currentMessages.length}`);

      if (!env.ANTHROPIC_API_KEY || !env.ANTHROPIC_API_KEY.startsWith("sk-ant-")) {
        return new Response(
          JSON.stringify({ type: "error", message: "AI service misconfigured." }),
          { status: 500, headers: { "Content-Type": "application/json" } },
        );
      }

      const claudeBody = {
        model,
        max_tokens: 1500,
        system: SYSTEM_PROMPT,
        tools: TOOLS,
        messages: currentMessages,
      };

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
        console.error("[chat] Claude fetch threw:", msg);
        return new Response(
          JSON.stringify({ type: "error", message: "Failed to reach AI service: " + msg }),
          { status: 502, headers: { "Content-Type": "application/json" } },
        );
      }

      if (!claudeResp.ok) {
        let errBody = "";
        try { errBody = await claudeResp.text(); } catch { errBody = "(no body)"; }
        console.error(`[chat] Claude API error ${claudeResp.status}:`, errBody.substring(0, 500));
        return new Response(
          JSON.stringify({ type: "error", message: `AI error (${claudeResp.status})` }),
          { status: 502, headers: { "Content-Type": "application/json" } },
        );
      }

      const claudeData = await claudeResp.json() as {
        content: Array<{ type: string; text?: string; id?: string; name?: string; input?: Record<string, unknown> }>;
        stop_reason: string;
      };

      console.log(`[chat] stop_reason=${claudeData.stop_reason} blocks=${claudeData.content?.length}`);

      if (claudeData.stop_reason === "tool_use") {
        const assistantContent: unknown[] = [];
        const toolResults: unknown[] = [];

        for (const block of claudeData.content) {
          if (block.type === "text" && block.text) {
            assistantContent.push({ type: "text", text: block.text });
            finalContent += block.text;
          } else if (block.type === "tool_use" && block.name && block.input) {
            console.log(`[chat] Tool call: ${block.name}`);
            assistantContent.push({
              type: "tool_use",
              id: block.id,
              name: block.name,
              input: block.input,
            });

            const outcome = await executeTool(block.name, block.input, env);
            if (outcome.sideEffect) actions.push(outcome.sideEffect);
            if (outcome.products) {
              for (const p of outcome.products) {
                if (!collectedProducts.find((cp) => cp.handle === p.handle)) {
                  collectedProducts.push(p);
                }
              }
            }

            toolResults.push({
              type: "tool_result",
              tool_use_id: block.id,
              content: outcome.result,
            });
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
        console.log(`[chat] Final: ${finalContent.length} chars`);
        break;
      }
    }

    // Strip any stray <product-card .../> tags in case the model emitted any
    finalContent = finalContent.replace(/<product-card[^>]*\/?>/g, "").trim();

    console.log(`[chat] Returning. content=${finalContent.length}, products=${collectedProducts.length}, actions=${actions.length}`);

    return new Response(
      JSON.stringify({
        type: "message",
        content: finalContent,
        products: collectedProducts,
        actions,
      }),
      { headers: { "Content-Type": "application/json", "Cache-Control": "no-cache" } },
    );
  } catch (err) {
    const msg = err instanceof Error ? `${err.message}\n${err.stack}` : String(err);
    console.error("[chat] UNCAUGHT:", msg);
    return new Response(
      JSON.stringify({ type: "error", message: "Internal error" }),
      { status: 500, headers: { "Content-Type": "application/json" } },
    );
  }
}
