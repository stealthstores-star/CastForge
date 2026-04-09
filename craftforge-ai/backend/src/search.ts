/**
 * Vector search against Cloudflare Vectorize + Shopify product lookup.
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
  theme?: string;
  price_max?: number;
  difficulty?: number;
}

interface Env {
  PRODUCTS: VectorizeIndex;
  VOYAGE_API_KEY: string;
  SHOPIFY_TOKEN: string;
  SHOPIFY_STORE: string;
}

/**
 * Embed a query string via Voyage AI.
 */
async function embedQuery(text: string, apiKey: string): Promise<number[]> {
  const resp = await fetch("https://api.voyageai.com/v1/embeddings", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${apiKey}`,
    },
    body: JSON.stringify({
      model: "voyage-3-lite",
      input: [text],
      input_type: "query",
    }),
  });

  if (!resp.ok) {
    throw new Error(`Voyage API error: ${resp.status} ${await resp.text()}`);
  }

  const data = (await resp.json()) as { data: Array<{ embedding: number[] }> };
  return data.data[0].embedding;
}

/**
 * Search products via Vectorize.
 */
export async function searchProducts(
  query: string,
  filters: SearchFilters,
  env: Env,
): Promise<ProductResult[]> {
  // Embed the query
  const queryVec = await embedQuery(query, env.VOYAGE_API_KEY);

  // Build Vectorize metadata filter
  const metadataFilter: Record<string, unknown> = {};
  if (filters.scale) metadataFilter.scale = filters.scale;
  if (filters.theme) metadataFilter.theme = filters.theme;
  if (filters.difficulty) metadataFilter.difficulty = filters.difficulty;

  // Query Vectorize
  const results = await env.PRODUCTS.query(queryVec, {
    topK: 20,
    returnMetadata: "all",
    filter: Object.keys(metadataFilter).length > 0 ? metadataFilter : undefined,
  });

  // Map to ProductResult, apply price filter client-side (Vectorize doesn't support range filters)
  const products: ProductResult[] = [];
  for (const match of results.matches) {
    const meta = match.metadata as Record<string, unknown> | undefined;
    if (!meta) continue;

    const price = Number(meta.price) || 0;
    if (filters.price_max && price > filters.price_max) continue;

    products.push({
      handle: String(meta.handle || ""),
      title: String(meta.title || ""),
      price,
      compare_at_price: meta.compare_at_price ? Number(meta.compare_at_price) : null,
      image: String(meta.image || ""),
      scale: String(meta.scale || ""),
      theme: String(meta.theme || ""),
      difficulty: Number(meta.difficulty) || 2,
      in_stock: meta.in_stock !== false,
      description_snippet: String(meta.description_snippet || ""),
    });

    if (products.length >= 8) break;
  }

  return products;
}

/**
 * Get full product details from Shopify.
 */
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

/**
 * Get complementary products by searching related terms.
 */
export async function getComplementaryProducts(
  productHandle: string,
  complementType: string,
  env: Env,
): Promise<ProductResult[]> {
  // First get the product to know what it is
  const product = await getProductDetails(productHandle, env);
  if (!product) return [];

  const title = String(product.title || "");

  // Build a search query based on complement type
  const queryMap: Record<string, string> = {
    paints: "hobby paint set brush primer for painting resin models",
    bases: `display base plinth scenic base for ${title}`,
    accessories: "hobby tools cutting mat magnifying lamp display case",
    matching_figures: `figures matching ${title} same theme same scale`,
    bundle: `similar to ${title} same category`,
  };

  const query = queryMap[complementType] || `accessories for ${title}`;
  return searchProducts(query, {}, env);
}
