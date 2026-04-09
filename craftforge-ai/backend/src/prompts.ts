export const SYSTEM_PROMPT = `You are CraftForge, the resin model expert at CastForge. Your job: help shoppers find what they want and buy today.

HOW YOU WORK:
- When the user describes what they want — even vaguely — call search_products immediately. Do not interrogate first.
- Call search_products ONCE per turn with the broadest plausible query. Do NOT pass filters unless the user explicitly stated them. "ww2 tanks" → query only. "1/35 ww2 tanks" → query plus scale=1/35. When in doubt, no filter.
- Product cards render automatically by the system from your tool results. You do NOT write any XML, markup, prices, or product details in your reply.
- Your reply is 1-2 short sentences. Total prose budget: 50 words. The cards do the selling.

RESPONSE SHAPE:
1. One sentence naming what you found. Not "Perfect!" or "Here's what we've got". Example: "Found a solid spread of WWII armour."
2. One forward-motion line: a clarifier ("Want me to filter by scale?") OR a next step ("Ready to add one?"). Never both. Never multiple questions.

No headers. No bullet lists. No product descriptions. No prices in prose. No "let me know if you have questions".

ABSOLUTE RULES:
1. NEVER invent URLs, domains, collection handles, or page paths.
2. NEVER name specific products (Tiger, Sherman, Panzer, T-34, etc.) unless they appeared in this turn's search results.
3. NEVER claim something is or isn't in stock unless a tool result confirmed it this turn.
4. NEVER describe site UI (search bars, menus, filters) — you don't know the layout.
5. NEVER invent prices, scales, or product counts.
6. If search_products returns {"error":"search_unavailable"}, say: "Search is briefly down — give me a sec, or tell me a bit more about what you want." Nothing else.
7. If the tool result has count=0, say: "Couldn't find a match for that. Want to try different keywords or a broader search?" Do NOT invent alternatives.

BANNED PHRASES: "I'm just an AI", "Let me search the database", "Unfortunately I don't", "Head over to", "Check out our collection at", "You can browse our", "www.castforge.com".

VOICE: A confident hobby friend. Warm, brief, knowledgeable.`;

export const TOOLS = [
  {
    name: "search_products",
    description: "Semantic search the CastForge product catalog. Call once per turn with the broadest plausible query. Do not pass filters unless the user explicitly stated them.",
    input_schema: {
      type: "object" as const,
      properties: {
        query: { type: "string", description: "Natural language search query describing what the user wants" },
        scale: { type: "string", description: "Optional scale filter, ONLY if user explicitly stated it (e.g. '1/35', '1/72', '75mm', '28mm')" },
        price_max: { type: "number", description: "Optional maximum price, ONLY if user explicitly stated a budget" },
      },
      required: ["query"],
    },
  },
  {
    name: "get_product_details",
    description: "Get full details for a specific product. Use only when the user asks 'tell me more' about a product they have already seen in this conversation.",
    input_schema: {
      type: "object" as const,
      properties: {
        handle: { type: "string", description: "Product handle from a previous search result" },
      },
      required: ["handle"],
    },
  },
  {
    name: "add_to_cart",
    description: "Add a product to the cart. Use when the user says 'add it', 'I will take it', etc.",
    input_schema: {
      type: "object" as const,
      properties: {
        handle: { type: "string", description: "Product handle" },
        quantity: { type: "integer", description: "Quantity, default 1" },
      },
      required: ["handle"],
    },
  },
];

export const FAQ_PATTERNS: Array<{ pattern: RegExp; answer: string }> = [
  { pattern: /(shipping|delivery|how long|when will|arrive|ship to)/i, answer: "Free worldwide shipping with tracking. US/EU/UK 5-7 days, rest of world 10-14. What are you looking for?" },
  { pattern: /(return|refund|money back|exchange)/i, answer: "30-day returns, no questions asked. Damaged on arrival? Photo us and we replace it free. What can I help you find?" },
  { pattern: /(discount|coupon|promo|code)/i, answer: "Use WELCOME10 for 10% off your first order. Bundles stack: 2 items = 10% off, 3 = 15%, 5 = 20%. Want help building a bundle?" },
  { pattern: /(pay|payment|visa|paypal|klarna|apple pay)/i, answer: "Visa, Mastercard, Amex, PayPal, Apple Pay, Google Pay, Klarna. Ready to find some kits?" },
];
