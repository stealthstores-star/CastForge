/**
 * CraftForge AI — Cloudflare Worker entry point.
 *
 * Endpoints:
 *   POST /chat    — main conversation (Claude + tool use)
 *   POST /search  — standalone product search
 *   POST /sync    — admin: re-embed changed products
 *   GET  /health  — health check
 */

import { handleChat } from "./chat";
import { searchProducts, type SearchFilters } from "./search";

interface Env {
  PRODUCTS: VectorizeIndex;
  ANTHROPIC_API_KEY: string;
  VOYAGE_API_KEY: string;
  SHOPIFY_TOKEN: string;
  SHOPIFY_STORE: string;
  MAX_MESSAGES_PER_SESSION: string;
  ADMIN_SECRET: string;
  ENVIRONMENT: string;
}

const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "POST, GET, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, Authorization",
};

function corsResponse(response: Response): Response {
  const headers = new Headers(response.headers);
  for (const [k, v] of Object.entries(CORS_HEADERS)) {
    headers.set(k, v);
  }
  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers,
  });
}

function jsonResponse(data: unknown, status = 200): Response {
  return corsResponse(
    new Response(JSON.stringify(data), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    // Handle CORS preflight
    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: CORS_HEADERS });
    }

    const url = new URL(request.url);
    const path = url.pathname;

    try {
      // Health check
      if (path === "/health" && request.method === "GET") {
        return jsonResponse({ status: "ok", timestamp: Date.now() });
      }

      // Chat endpoint
      if (path === "/chat" && request.method === "POST") {
        const body = (await request.json()) as Record<string, unknown>;

        if (!body.message || typeof body.message !== "string") {
          return jsonResponse({ error: "message is required" }, 400);
        }

        const chatResp = await handleChat(
          {
            message: body.message as string,
            history: (body.history as Array<{ role: "user" | "assistant"; content: string }>) || [],
            sessionId: (body.sessionId as string) || "anonymous",
            context: body.context as Record<string, unknown> | undefined,
          },
          env,
        );

        return corsResponse(chatResp);
      }

      // Search endpoint
      if (path === "/search" && request.method === "POST") {
        const body = (await request.json()) as Record<string, unknown>;

        if (!body.query || typeof body.query !== "string") {
          return jsonResponse({ error: "query is required" }, 400);
        }

        const filters: SearchFilters = {
          scale: body.scale as string | undefined,
          theme: body.theme as string | undefined,
          price_max: body.price_max as number | undefined,
          difficulty: body.difficulty as number | undefined,
        };

        const results = await searchProducts(body.query as string, filters, env);
        return jsonResponse({ results });
      }

      // Sync endpoint (admin only)
      if (path === "/sync" && request.method === "POST") {
        const auth = request.headers.get("Authorization");
        if (auth !== `Bearer ${env.ADMIN_SECRET}`) {
          return jsonResponse({ error: "unauthorized" }, 401);
        }

        // Trigger product sync — fetch updated products and re-embed
        const since = new Date();
        since.setDate(since.getDate() - 1);
        const sinceISO = since.toISOString();

        const shopifyUrl = `https://${env.SHOPIFY_STORE}/admin/api/2024-10/products.json?updated_at_min=${sinceISO}&limit=250&fields=id,title,handle,body_html,tags,variants,images`;
        const resp = await fetch(shopifyUrl, {
          headers: { "X-Shopify-Access-Token": env.SHOPIFY_TOKEN },
        });

        if (!resp.ok) {
          return jsonResponse({ error: `Shopify error: ${resp.status}` }, 502);
        }

        const data = (await resp.json()) as { products: Array<Record<string, unknown>> };
        const count = data.products?.length || 0;

        // For each product, embed and upsert to Vectorize
        // (In production, batch these via Voyage API)
        let synced = 0;
        for (const product of data.products || []) {
          try {
            const title = String(product.title || "");
            const desc = String(product.body_html || "")
              .replace(/<[^>]+>/g, " ")
              .substring(0, 500);
            const tags = String(product.tags || "");
            const scale = extractScale(tags);
            const theme = extractTheme(tags, title);

            const embText = `${title}. ${desc}. Scale: ${scale}. Theme: ${theme}`;

            // Embed via Voyage
            const embResp = await fetch("https://api.voyageai.com/v1/embeddings", {
              method: "POST",
              headers: {
                "Content-Type": "application/json",
                Authorization: `Bearer ${env.VOYAGE_API_KEY}`,
              },
              body: JSON.stringify({
                model: "voyage-3-lite",
                input: [embText],
                input_type: "document",
              }),
            });

            if (!embResp.ok) continue;
            const embData = (await embResp.json()) as { data: Array<{ embedding: number[] }> };
            const vector = embData.data[0].embedding;

            const variants = product.variants as Array<Record<string, unknown>> | undefined;
            const images = product.images as Array<Record<string, unknown>> | undefined;
            const price = variants?.[0]?.price ? Number(variants[0].price) : 0;
            const compareAt = variants?.[0]?.compare_at_price ? Number(variants[0].compare_at_price) : null;
            const image = images?.[0]?.src ? String(images[0].src) : "";

            await env.PRODUCTS.upsert([
              {
                id: String(product.id),
                values: vector,
                metadata: {
                  handle: String(product.handle),
                  title,
                  price,
                  compare_at_price: compareAt,
                  image,
                  scale,
                  theme,
                  difficulty: 2,
                  in_stock: true,
                  description_snippet: desc.substring(0, 200),
                },
              },
            ]);

            synced++;
          } catch {
            // Skip failed products
          }
        }

        return jsonResponse({ synced, found: count });
      }

      // Admin stats endpoint
      if (path === "/admin/stats" && request.method === "GET") {
        const auth = request.headers.get("Authorization");
        if (auth !== `Bearer ${env.ADMIN_SECRET}`) {
          return jsonResponse({ error: "unauthorized" }, 401);
        }

        return jsonResponse({
          status: "ok",
          environment: env.ENVIRONMENT,
          note: "Full analytics via Cloudflare dashboard. This is a basic health endpoint.",
        });
      }

      return jsonResponse({ error: "Not found" }, 404);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Internal error";
      return jsonResponse({ error: message }, 500);
    }
  },

  // Cron trigger for daily sync
  async scheduled(event: ScheduledEvent, env: Env): Promise<void> {
    // Self-call the sync endpoint
    const url = `https://craftforge-ai.castforge.workers.dev/sync`;
    await fetch(url, {
      method: "POST",
      headers: { Authorization: `Bearer ${env.ADMIN_SECRET}` },
    });
  },
};

// Helper: extract scale from tags
function extractScale(tags: string): string {
  const match = tags.match(/scale:([\w-]+)/);
  if (match) return match[1].replace("-", "/");
  return "";
}

// Helper: extract theme from tags/title
function extractTheme(tags: string, title: string): string {
  const lower = (tags + " " + title).toLowerCase();
  if (/ww2|wwii|world war|german|soviet|sherman|tiger|panzer/.test(lower)) return "wwii";
  if (/modern|contemporary|seal|swat/.test(lower)) return "modern";
  if (/fantasy|dragon|orc|elf|dwarf|wizard|knight|barbarian/.test(lower)) return "fantasy";
  if (/sci-?fi|cyber|robot|mech|space/.test(lower)) return "scifi";
  if (/anime|manga|schoolgirl|waifu/.test(lower)) return "anime";
  if (/car|motorcycle|ferrari|porsche|mustang/.test(lower)) return "cars";
  if (/terrain|building|ruin|tree|base/.test(lower)) return "terrain";
  if (/roman|napoleon|viking|samurai|medieval/.test(lower)) return "historical";
  return "";
}
