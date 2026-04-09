export const SYSTEM_PROMPT = `You are CraftForge, the resin model expert at CastForge. Your #1 job: help shoppers find what they want and buy it today. You're a friendly hobby expert, not a chatbot.

CORE BEHAVIOR:
- Get to a product recommendation in 2 messages MAX. Don't interrogate.
- If user gives ANY signal of intent (scale, theme, era, character type, gift), search immediately and show products.
- Always show 4-6 products as cards with REAL prices and stock status.
- Every recommendation includes ONE sentence on why it's perfect for them — make them feel understood.
- Suggest complementary items naturally: "These go great with..." (paints, bases, accessories)
- If they pick one, immediately offer 2-3 related upsells: "Most people also grab X for the diorama base"
- Mention free worldwide shipping, 30-day returns, and bulk discounts (Buy 3 = 15% off, Buy 5 = 20% off) when relevant
- If they hesitate, offer the 10% welcome discount code WELCOME10
- Close every response with a soft CTA or question that moves them toward purchase

UPSELL TRIGGERS:
- User adds to cart → "Great choice! Want to add the matching crew/base/accessories?"
- User hits $40 → "You're $10 away from unlocking the bundle discount"
- User browsing many products → "Want me to put together a starter bundle?"
- User asks about painting → recommend paint codes + brushes
- User asks about display → recommend bases + cases
- User mentions a character → suggest the whole faction/army

FAQ HANDLING (answer instantly, don't deflect):
- Shipping: "Free worldwide shipping, 5-7 days to US/EU/UK, 10-14 days elsewhere. All orders tracked."
- Returns: "30-day returns, no questions asked. Damaged items replaced free."
- Quality: "Premium resin from top casters worldwide. Unpainted unless stated."
- Customs: "We handle customs for most countries. UK/EU/US duty-free under $150."
- Painting: "All models are unpainted resin — paint not included unless stated. We recommend Citadel or Vallejo."
- Scale: "Use our scale guide at /pages/scale-guide for visual comparisons."
- Stock: "All listed items are in stock. Restocks happen weekly."
- Bundle discount: "Buy 2 = 10% off, Buy 3 = 15% off, Buy 5 = 20% off — auto-applied at checkout."
- Payment: "We accept Visa, Mastercard, Amex, PayPal, Apple Pay, Google Pay, Klarna (4 payments)."

NEVER:
- Say "I'm just an AI"
- Apologize for not knowing — search instead
- Recommend products that aren't in the catalog
- Be pushy or use fake urgency
- Make up prices, stock, or specs

BANNED PHRASES:
- "I'd recommend checking..."
- "Unfortunately I don't..."
- "As an AI..."
- "Let me search the database..."

When presenting products, format each as a JSON block the frontend can parse:
<product-card handle="..." title="..." price="..." compare_at="..." image="..." scale="..." rationale="..." />

VOICE: Confident hobby friend who happens to work at the best resin store online. Warm, knowledgeable, slightly enthusiastic. Uses light hobby jargon (kit-bashing, basing, layering, washes) when appropriate.

Current store has 14,000+ resin models across 12 categories. Always use the search_products tool to find real products.`;

export const TOOLS = [
  {
    name: "search_products",
    description: "Semantic search the CastForge product catalog. Returns products matching the user's intent. Use this whenever the user describes what they want.",
    input_schema: {
      type: "object" as const,
      properties: {
        query: { type: "string", description: "Natural language search query describing what the user wants" },
        scale: { type: "string", description: "Optional scale filter (e.g. '1/35', '1/72', '75mm', '28mm')" },
        theme: { type: "string", description: "Optional theme: wwii, modern, fantasy, scifi, anime, historical, cars, terrain" },
        price_max: { type: "number", description: "Optional maximum price in USD" },
        difficulty: { type: "integer", description: "Optional painting difficulty 1=beginner 2=intermediate 3=advanced" },
      },
      required: ["query"],
    },
  },
  {
    name: "get_product_details",
    description: "Get full details for a specific product. Use when user asks 'tell me more' or wants specs.",
    input_schema: {
      type: "object" as const,
      properties: {
        handle: { type: "string", description: "Product handle from search results" },
      },
      required: ["handle"],
    },
  },
  {
    name: "get_complementary_products",
    description: "Find products that pair well with one the user likes. Use for upselling after they show interest.",
    input_schema: {
      type: "object" as const,
      properties: {
        product_handle: { type: "string" },
        complement_type: {
          type: "string",
          enum: ["paints", "bases", "accessories", "matching_figures", "bundle"],
          description: "Type of complementary product to find",
        },
      },
      required: ["product_handle", "complement_type"],
    },
  },
  {
    name: "add_to_cart",
    description: "Add a product to the user's cart. Use when they say 'add it', 'I'll take it', 'buy', etc.",
    input_schema: {
      type: "object" as const,
      properties: {
        handle: { type: "string", description: "Product handle" },
        quantity: { type: "integer", description: "Quantity to add, default 1" },
      },
      required: ["handle"],
    },
  },
  {
    name: "apply_discount",
    description: "Apply a discount code to the user's session. Use when offering WELCOME10 or other promos.",
    input_schema: {
      type: "object" as const,
      properties: {
        code: { type: "string", description: "Discount code" },
      },
      required: ["code"],
    },
  },
];

export const FAQ_PATTERNS: Array<{ pattern: RegExp; answer: string }> = [
  { pattern: /(shipping|delivery|how long|when will|arrive|ship to)/i, answer: "Free worldwide shipping with tracking! US/EU/UK: 5-7 days, rest of world: 10-14 days. Every order gets a tracking number. Want me to help you find something to ship?" },
  { pattern: /(return|refund|money back|not happy|exchange)/i, answer: "30-day returns, no questions asked. If anything arrives damaged, send us a photo and we'll replace it free — no return needed. Browse with confidence! What are you looking for?" },
  { pattern: /(discount|coupon|promo|code|sale|deal|cheaper)/i, answer: "Great timing! Use **WELCOME10** for 10% off your first order. Plus bundle savings stack automatically: 2 items = 10% off, 3 = 15%, 5 = 20%. Want me to help build a bundle?" },
  { pattern: /(pay|payment|visa|paypal|klarna|apple pay)/i, answer: "We accept Visa, Mastercard, Amex, PayPal, Apple Pay, Google Pay, and Klarna (split into 4 payments). All transactions are secured with Shopify's encryption. Ready to find some models?" },
  { pattern: /(custom|duty|tax|import|vat)/i, answer: "Good question — orders to the US, EU, and UK are typically duty-free under $150. For other countries, local customs may apply but it's usually minimal for models. What can I help you find?" },
  { pattern: /(paint|unpaint|color|prime|primer)/i, answer: "All our models ship unpainted — that's half the fun! We recommend Citadel or Vallejo paints. Check the 'Recommended Paints' tab on any product page for specific colour suggestions. Want me to find a model that matches your skill level?" },
  { pattern: /(scale guide|what scale|which scale|size)/i, answer: "Check our interactive scale guide at /pages/scale-guide — it shows every scale with a visual comparison to a coin. Quick summary: 28mm for tabletop gaming, 1/35 for detailed military, 75mm for display pieces. What scale interests you?" },
  { pattern: /(stock|in stock|available|out of stock|restock)/i, answer: "Everything listed on the store is in stock and ships within 24 hours. We restock weekly. If something sells out, it's temporarily hidden until the next batch arrives. What are you looking for?" },
  { pattern: /(quality|material|resin|detail|cast)/i, answer: "All our models are high-quality resin from established casters. Resin captures much finer detail than plastic injection — sharper panel lines, crisper faces, better texture. It's the material of choice for serious hobbyists. Want to see some examples?" },
];
