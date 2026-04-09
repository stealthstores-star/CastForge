/**
 * Vector search against Cloudflare Vectorize.
 */

export interface ProductResult {
  handle: string;
  title: string;
  price: number;
  compare_at_price: number | null;
  image: string;
  scale: string;
  theme: string;
  difficulty: number;
  in_stock: boolean;
  description_snippet: string;
}

export interface SearchFilters {
  scale?: string;
  price_max?: number;
}

interface Env {
  PRODUCTS: VectorizeIndex;
  VOYAGE_API_KEY: string;
  SHOPIFY_TOKEN: string;
  SHOPIFY_STORE: string;
}

async function embedQuery(text: string, apiKey: string): Promise<number[]> {
  console.log(`[search] embedQuery: "${text.substring(0, 80)}..."`);
  if (!apiKey) throw new Error("VOYAGE_API_KEY is not set");

  const resp = await fetch("https://api.voyageai.com/v1/embeddings", {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${apiKey}` },
    body: JSON.stringify({ model: "voyage-3-lite", input: [text], input_type: "query" }),
  });

  if (!resp.ok) {
    let body = "";
    try { body = await resp.text(); } catch {}
    throw new Error(`Voyage API error ${resp.status}: ${body.substring(0, 200)}`);
  }

  const data = (await resp.json()) as { data: Array<{ embedding: number[] }> };
  console.log(`[search] embedQuery: got ${data.data[0].embedding.length}-dim vector`);
  return data.data[0].embedding;
}

function metaToProduct(meta: Record<string, unknown>): ProductResult {
  return {
    handle: String(meta.handle || ""),
    title: String(meta.title || ""),
    price: Number(meta.price) || 0,
    compare_at_price: meta.compare_at_price ? Number(meta.compare_at_price) : null,
    image: String(meta.image || ""),
    scale: String(meta.scale || ""),
    theme: String(meta.theme || ""),
    difficulty: Number(meta.difficulty) || 2,
    in_stock: meta.in_stock !== false,
    description_snippet: String(meta.description_snippet || ""),
  };
}

export async function searchProducts(
  query: string,
  filters: SearchFilters,
  env: Env,
): Promise<ProductResult[]> {
  console.log(`[search] searchProducts: query="${query}" filters=`, JSON.stringify(filters));

  const queryVec = await embedQuery(query, env.VOYAGE_API_KEY);

  const metadataFilter: Record<string, unknown> = {};
  if (filters.scale) metadataFilter.scale = filters.scale;
  const hasFilters = Object.keys(metadataFilter).length > 0;

  console.log("[search] Querying Vectorize...", hasFilters ? `filters: ${JSON.stringify(metadataFilter)}` : "no filters");
  let results: VectorizeMatches;
  try {
    results = await env.PRODUCTS.query(queryVec, {
      topK: 30,
      returnMetadata: "all",
      filter: hasFilters ? metadataFilter : undefined,
    });
    console.log(`[search] Vectorize returned ${results.matches.length} matches`);
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    console.error("[search] Vectorize query FAILED:", msg);
    throw new Error(`Vectorize query failed: ${msg}`);
  }

  if (results.matches.length === 0 && hasFilters) {
    console.log("[search] Zero matches with filters, retrying without filters");
    try {
      results = await env.PRODUCTS.query(queryVec, { topK: 30, returnMetadata: "all" });
      console.log(`[search] Fallback returned ${results.matches.length} matches`);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      console.error("[search] Fallback query FAILED:", msg);
    }
  }

  const seenHandles = new Set<string>();
  const products: ProductResult[] = [];
  for (const match of results.matches) {
    const meta = match.metadata as Record<string, unknown> | undefined;
    if (!meta) continue;
    const p = metaToProduct(meta);
    if (!p.image) continue;
    if (!p.in_stock) continue;
    if (!p.handle) continue;
    if (seenHandles.has(p.handle)) continue;
    if (filters.price_max && p.price > filters.price_max) continue;
    seenHandles.add(p.handle);
    products.push(p);
    if (products.length >= 6) break;
  }

  console.log(`[search] Returning ${products.length} products after filter/dedupe`);
  return products;
}

export async function getProductDetails(
  handle: string,
  env: Env,
): Promise<Record<string, unknown> | null> {
  const url = `https://${env.SHOPIFY_STORE}/products/${handle}.json`;
  const resp = await fetch(url, {
    headers: { "X-Shopify-Access-Token": env.SHOPIFY_TOKEN },
  });
  if (!resp.ok) return null;
  const data = (await resp.json()) as { product: Record<string, unknown> };
  return data.product;
}

export async function getComplementaryProducts(
  productHandle: string,
  complementType: string,
  env: Env,
): Promise<ProductResult[]> {
  const product = await getProductDetails(productHandle, env);
  if (!product) return [];
  const title = String(product.title || "");
  const queryMap: Record<string, string> = {
    paints: "hobby paint set brush primer for painting resin models",
    bases: `display base plinth scenic base for ${title}`,
    accessories: "hobby tools cutting mat magnifying lamp display case",
    matching_figures: `figures matching ${title} same scale`,
    bundle: `similar to ${title} same category`,
  };
  const query = queryMap[complementType] || `accessories for ${title}`;
  return searchProducts(query, {}, env);
}
