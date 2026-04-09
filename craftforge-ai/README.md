# CraftForge AI — Shopping Assistant for CastForge

AI-powered resin model expert that helps shoppers find products and buy them.
Uses Claude for reasoning, Voyage AI for embeddings, Cloudflare Vectorize for
vector search, and a vanilla JS chat widget on the storefront.

## Architecture

```
┌──────────────┐     ┌────────────────────┐     ┌──────────────┐
│  Chat Widget │────▶│  Cloudflare Worker  │────▶│   Claude AI  │
│  (Shopify)   │◀────│  (Edge deployed)    │◀────│  (Anthropic) │
└──────────────┘     │                    │     └──────────────┘
                     │  ┌──────────────┐  │
                     │  │  Vectorize   │  │     ┌──────────────┐
                     │  │  (Vector DB) │◀─┼─────│  Voyage AI   │
                     │  └──────────────┘  │     │  (Embeddings)│
                     └────────────────────┘     └──────────────┘
```

## Cost per conversation

| Component | Cost |
|-----------|------|
| Claude Sonnet 4.6 (first 3 messages) | ~$0.06 |
| Claude Haiku 4.5 (follow-ups) | ~$0.02 |
| Voyage embed query | ~$0.0001 |
| Cloudflare Worker | ~$0.0001 |
| **Total per chat** | **~$0.05-0.15** |

Break-even: 1 sale per 30 chats at $20 AOV.

## Deployment

### 1. Deploy the Worker

```bash
cd backend
npm install
wrangler login

# Create the vector index
wrangler vectorize create castforge-products --dimensions=512 --metric=cosine

# Set secrets
wrangler secret put ANTHROPIC_API_KEY
wrangler secret put VOYAGE_API_KEY
wrangler secret put SHOPIFY_TOKEN
wrangler secret put ADMIN_SECRET

# Deploy
wrangler deploy
```

### 2. Embed all products

```bash
cd ../scripts
pip install -r requirements.txt

export VOYAGE_API_KEY="your-key"
export SHOPIFY_TOKEN="your-token"
export SHOPIFY_STORE="v614bh-2z.myshopify.com"
export CF_ACCOUNT_ID="your-cf-account-id"
export CF_API_TOKEN="your-cf-api-token"

python3 embed_products.py
```

This takes ~10 minutes and costs ~$3-5 for 14k products.

### 3. Add to Shopify theme

Upload the frontend files as theme assets:
- `frontend/craftforge-widget.js` → Shopify theme assets
- `frontend/craftforge-widget.css` → Shopify theme assets

Copy `theme-integration/craftforge.liquid` → theme snippets.

Add to `layout/theme.liquid` before `</body>`:
```liquid
{% render 'craftforge' %}
```

### 4. Test

1. Open the store
2. Click the orange chat bubble (bottom-right)
3. Try: "Show me 1/35 WWII tanks"
4. Verify product cards appear with real data
5. Click "Quick Add" and verify cart updates

### 5. Daily sync

The Worker has a Cloudflare Cron Trigger that runs daily at 3am UTC,
re-embedding any products updated in the last 24 hours.

You can also trigger manually:
```bash
curl -X POST https://craftforge-ai.castforge.workers.dev/sync \
  -H "Authorization: Bearer YOUR_ADMIN_SECRET"
```

## Endpoints

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/chat` | POST | None | Main conversation |
| `/search` | POST | None | Standalone product search |
| `/sync` | POST | Admin | Re-embed updated products |
| `/health` | GET | None | Health check |
| `/admin/stats` | GET | Admin | Basic stats |

## Conversion features

- **FAQ fast-path**: Common questions answered instantly without Claude call
- **Smart model selection**: Sonnet for initial messages, Haiku for follow-ups
- **Tool use**: Claude searches products, adds to cart, applies discounts
- **Upsell logic**: Complementary product suggestions after every add-to-cart
- **Session persistence**: Conversation and preferences survive page reloads
- **Idle nudge**: Prompts user after 30s of inactivity when products are shown
- **Quick-pick chips**: Context-aware shortcuts that evolve with the conversation
- **Cart integration**: Products added directly from chat, cart drawer opens

## Files

```
craftforge-ai/
├── backend/
│   ├── wrangler.toml          # Cloudflare Workers config
│   ├── package.json
│   ├── tsconfig.json
│   └── src/
│       ├── index.ts           # Worker entry + router
│       ├── chat.ts            # Claude conversation handler
│       ├── search.ts          # Vectorize search + Voyage embeddings
│       └── prompts.ts         # System prompt + tools + FAQ patterns
├── scripts/
│   ├── embed_products.py      # One-time embedding job
│   ├── sync_products.py       # Daily incremental sync
│   └── requirements.txt
├── frontend/
│   ├── craftforge-widget.js   # Chat widget (vanilla JS)
│   └── craftforge-widget.css  # Widget styles
├── theme-integration/
│   └── craftforge.liquid      # Shopify snippet
└── README.md
```
