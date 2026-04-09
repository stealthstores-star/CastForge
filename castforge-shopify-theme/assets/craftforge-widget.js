/**
 * CraftForge AI — Chat widget for Shopify storefronts.
 * Vanilla JS, no dependencies. Communicates with Cloudflare Worker backend.
 */
(function () {
  'use strict';

  if (window.__CRAFTFORGE_LOADED) {
    console.warn('[CraftForge] Already initialized — skipping duplicate');
    return;
  }
  window.__CRAFTFORGE_LOADED = true;

  console.log('[CraftForge] Widget script loaded');
  console.log('[CraftForge] CRAFTFORGE_CONFIG:', window.CRAFTFORGE_CONFIG);

  var CONFIG = window.CRAFTFORGE_CONFIG || {};
  var WORKER_URL = CONFIG.workerUrl || '';
  var STORE_URL = CONFIG.storeUrl || '';
  var SESSION_KEY = 'craftforge_session';
  var PREFS_KEY = 'craftforge_prefs';

  if (!WORKER_URL) {
    console.warn('[CraftForge] No workerUrl configured — widget disabled. Set window.CRAFTFORGE_CONFIG.workerUrl before loading this script.');
    return;
  }

  console.log('[CraftForge] Worker URL:', WORKER_URL);

  // ── State ──
  var state = {
    open: false,
    history: [],
    sessionId: '',
    sending: false,
    preferences: {},
  };

  // Load persisted session
  try {
    var saved = JSON.parse(localStorage.getItem(SESSION_KEY) || 'null');
    if (saved && saved.history) {
      state.history = saved.history;
      state.sessionId = saved.sessionId || generateId();
    } else {
      state.sessionId = generateId();
    }
    var prefs = JSON.parse(localStorage.getItem(PREFS_KEY) || '{}');
    state.preferences = prefs;
  } catch (e) {
    state.sessionId = generateId();
  }

  function generateId() {
    return 'cf_' + Date.now().toString(36) + Math.random().toString(36).substr(2, 6);
  }

  function saveSession() {
    try {
      localStorage.setItem(SESSION_KEY, JSON.stringify({
        history: state.history.slice(-40),
        sessionId: state.sessionId,
      }));
    } catch (e) {}
  }

  function savePrefs() {
    try { localStorage.setItem(PREFS_KEY, JSON.stringify(state.preferences)); } catch (e) {}
  }

  // ── DOM ──
  function createWidget() {
    console.log('[CraftForge] Creating widget DOM...');

    if (!document.body) {
      console.error('[CraftForge] document.body not available — deferring init');
      document.addEventListener('DOMContentLoaded', function () { createWidget(); });
      return null;
    }

    // Bubble
    var bubble = document.createElement('button');
    bubble.type = 'button';
    bubble.className = 'cf-ai-bubble' + (state.history.length === 0 ? ' cf-ai-bubble--pulse' : '');
    bubble.setAttribute('aria-label', 'Open CraftForge AI assistant');
    bubble.innerHTML = '<svg viewBox="0 0 24 24"><path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm0 14H5.17L4 17.17V4h16v12z"/><path d="M7 9h2v2H7zm4 0h2v2h-2zm4 0h2v2h-2z"/></svg>';
    bubble.addEventListener('click', function () {
      console.log('[CraftForge] Bubble clicked');
      togglePanel();
    });

    // Panel
    var panel = document.createElement('div');
    panel.className = 'cf-ai-panel';
    panel.id = 'cf-ai-panel';
    panel.innerHTML = [
      '<div class="cf-ai-header">',
      '  <div class="cf-ai-header__title">',
      '    <div class="cf-ai-header__icon"><svg viewBox="0 0 24 24"><path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2z"/></svg></div>',
      '    <div class="cf-ai-header__text"><h3>CRAFTFORGE AI</h3><span>Resin model expert</span></div>',
      '  </div>',
      '  <div class="cf-ai-header__actions">',
      '    <button type="button" class="cf-ai-header__btn" id="cf-ai-reset" title="Start over">↻</button>',
      '    <button type="button" class="cf-ai-header__btn" id="cf-ai-close" title="Close">✕</button>',
      '  </div>',
      '</div>',
      '<div class="cf-ai-messages" id="cf-ai-messages"></div>',
      '<div class="cf-ai-input">',
      '  <input type="text" class="cf-ai-input__field" id="cf-ai-input" placeholder="Ask me anything about resin models..." autocomplete="off">',
      '  <button type="button" class="cf-ai-input__send" id="cf-ai-send" aria-label="Send">',
      '    <svg viewBox="0 0 24 24"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>',
      '  </button>',
      '</div>',
    ].join('\n');

    document.body.appendChild(bubble);
    document.body.appendChild(panel);

    // Bind events
    var closeBtn = document.getElementById('cf-ai-close');
    var resetBtn = document.getElementById('cf-ai-reset');
    var sendBtn = document.getElementById('cf-ai-send');
    var inputEl = document.getElementById('cf-ai-input');

    console.log('[CraftForge] DOM elements found:', {
      closeBtn: !!closeBtn,
      resetBtn: !!resetBtn,
      sendBtn: !!sendBtn,
      inputEl: !!inputEl,
    });

    if (closeBtn) closeBtn.addEventListener('click', togglePanel);
    if (resetBtn) resetBtn.addEventListener('click', resetConversation);

    if (sendBtn) {
      sendBtn.addEventListener('click', function (e) {
        console.log('[CraftForge] Send button clicked');
        e.preventDefault();
        sendMessage();
      });
      console.log('[CraftForge] Send button listener attached');
    } else {
      console.error('[CraftForge] Send button #cf-ai-send not found!');
    }

    if (inputEl) {
      inputEl.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' && !e.shiftKey) {
          console.log('[CraftForge] Enter key pressed in input');
          e.preventDefault();
          sendMessage();
        }
      });
      console.log('[CraftForge] Input keydown listener attached');
    } else {
      console.error('[CraftForge] Input #cf-ai-input not found!');
    }

    // Render existing history
    if (state.history.length > 0) {
      state.history.forEach(function (msg) {
        appendMessage(msg.role, msg.content, true);
      });
    }

    console.log('[CraftForge] Widget created successfully');
    return { bubble: bubble, panel: panel };
  }

  var dom = createWidget();
  if (!dom) {
    console.error('[CraftForge] createWidget returned null — widget not initialized');
    return;
  }

  // ── Panel toggle ──
  function togglePanel() {
    state.open = !state.open;
    console.log('[CraftForge] Panel toggled, open:', state.open);
    dom.panel.classList.toggle('cf-ai-panel--open', state.open);
    dom.bubble.classList.toggle('cf-ai-bubble--hidden', state.open);

    if (state.open) {
      if (state.history.length === 0) {
        showWelcome();
      }
      setTimeout(function () {
        var input = document.getElementById('cf-ai-input');
        if (input) input.focus();
      }, 300);
      scrollToBottom();
    }
  }

  function showWelcome() {
    if (state.preferences.lastScale || state.preferences.lastTheme) {
      var pref = state.preferences;
      var msg = "Welcome back! Last time you were looking at " +
        (pref.lastScale ? pref.lastScale + " " : "") +
        (pref.lastTheme ? pref.lastTheme + " " : "") +
        "models. Want to pick up where we left off, or something new?";
      appendMessage('assistant', msg);
      state.history.push({ role: 'assistant', content: msg });
    } else {
      var welcome = "Hey! I'm CraftForge — your resin model expert. Tell me what you're looking for and I'll find the perfect kits for you.";
      appendMessage('assistant', welcome);
      state.history.push({ role: 'assistant', content: welcome });
    }

    showChips(getInitialChips());
    saveSession();
  }

  function getInitialChips() {
    return [
      { label: "I'm new to this", msg: "I'm new to miniatures and resin models. What do you recommend for a beginner?" },
      { label: "Browse by scale", msg: "What scales do you have? Help me understand the differences." },
      { label: "Help me pick a gift", msg: "I'm looking for a gift for someone who likes miniatures." },
      { label: "What's popular", msg: "Show me your most popular models right now." },
    ];
  }

  function getPostProductChips() {
    return [
      { label: "Cheaper options", msg: "Show me cheaper alternatives" },
      { label: "More like this", msg: "Show me more like these" },
      { label: "Different scale", msg: "Same theme but a different scale" },
    ];
  }

  function getPostCartChips() {
    return [
      { label: "What else?", msg: "What else would go well with what I just added?" },
      { label: "Any deals?", msg: "Are there any bundle deals I should know about?" },
      { label: "Checkout now", msg: "I'm ready to checkout" },
    ];
  }

  // ── Messages ──
  function appendMessage(role, content, skipScroll) {
    var container = document.getElementById('cf-ai-messages');
    if (!container) {
      console.error('[CraftForge] Messages container #cf-ai-messages not found');
      return;
    }
    var div = document.createElement('div');
    div.className = 'cf-ai-msg cf-ai-msg--' + (role === 'user' ? 'user' : 'bot');

    var parsed = parseProductCards(content);
    div.innerHTML = parsed.html;
    container.appendChild(div);

    if (parsed.products.length > 0) {
      var productsDiv = document.createElement('div');
      productsDiv.className = 'cf-ai-products';
      parsed.products.forEach(function (p) {
        productsDiv.appendChild(createProductCard(p));
      });
      container.appendChild(productsDiv);
      showChips(getPostProductChips());
    }

    if (!skipScroll) scrollToBottom();
  }

  function parseProductCards(content) {
    var products = [];
    var regex = /<product-card\s+([^>]+)\/>/g;
    var match;
    while ((match = regex.exec(content)) !== null) {
      var attrs = {};
      var attrRegex = /(\w+)="([^"]*)"/g;
      var am;
      while ((am = attrRegex.exec(match[1])) !== null) {
        attrs[am[1]] = am[2];
      }
      products.push(attrs);
    }

    var html = content.replace(/<product-card[^>]*\/>/g, '');
    html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/\n/g, '<br>');

    return { html: html, products: products };
  }

  function createProductCard(p) {
    var card = document.createElement('div');
    card.className = 'cf-ai-product';

    var savings = '';
    if (p.compare_at && parseFloat(p.compare_at) > parseFloat(p.price)) {
      savings = '<span class="cf-ai-product__was">$' + parseFloat(p.compare_at).toFixed(2) + '</span>';
    }

    card.innerHTML = [
      '<img class="cf-ai-product__img" src="' + (p.image || '') + '" alt="' + (p.title || '') + '" width="72" height="72" loading="lazy">',
      '<div class="cf-ai-product__info">',
      '  <div class="cf-ai-product__title">' + (p.title || '') + '</div>',
      '  <div class="cf-ai-product__prices">',
      '    <span class="cf-ai-product__price">$' + parseFloat(p.price || 0).toFixed(2) + '</span>',
      '    ' + savings,
      '  </div>',
      p.rationale ? '  <div class="cf-ai-product__rationale">' + p.rationale + '</div>' : '',
      '  <div class="cf-ai-product__actions">',
      '    <button type="button" class="cf-ai-product__btn cf-ai-product__btn--add" data-handle="' + (p.handle || '') + '">Quick Add</button>',
      '    <a href="/products/' + (p.handle || '') + '" target="_blank" class="cf-ai-product__btn cf-ai-product__btn--view">View</a>',
      '  </div>',
      '</div>',
    ].join('\n');

    card.querySelector('.cf-ai-product__btn--add').addEventListener('click', function () {
      addToCart(p.handle, this);
    });

    return card;
  }

  function showChips(chips) {
    var container = document.getElementById('cf-ai-messages');
    if (!container) return;
    var old = container.querySelector('.cf-ai-chips');
    if (old) old.remove();

    var div = document.createElement('div');
    div.className = 'cf-ai-chips';
    chips.forEach(function (chip) {
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'cf-ai-chip';
      btn.textContent = chip.label;
      btn.addEventListener('click', function () {
        console.log('[CraftForge] Chip clicked:', chip.label);
        div.remove();
        document.getElementById('cf-ai-input').value = chip.msg;
        sendMessage();
      });
      div.appendChild(btn);
    });
    container.appendChild(div);
    scrollToBottom();
  }

  function showTyping() {
    var container = document.getElementById('cf-ai-messages');
    if (!container) return;
    var div = document.createElement('div');
    div.className = 'cf-ai-typing';
    div.id = 'cf-ai-typing';
    div.innerHTML = '<span></span><span></span><span></span>';
    container.appendChild(div);
    scrollToBottom();
  }

  function hideTyping() {
    var el = document.getElementById('cf-ai-typing');
    if (el) el.remove();
  }

  function scrollToBottom() {
    var container = document.getElementById('cf-ai-messages');
    if (container) {
      setTimeout(function () { container.scrollTop = container.scrollHeight; }, 50);
    }
  }

  // ── Send ──
  function sendMessage() {
    console.log('[CraftForge] sendMessage() called');
    console.log('[CraftForge]   state.sending:', state.sending);

    if (state.sending) {
      console.log('[CraftForge]   Blocked: already sending');
      return;
    }

    var input = document.getElementById('cf-ai-input');
    if (!input) {
      console.error('[CraftForge]   Input element not found');
      return;
    }

    var msg = input.value.trim();
    console.log('[CraftForge]   Message:', JSON.stringify(msg));

    if (!msg) {
      console.log('[CraftForge]   Blocked: empty message');
      return;
    }

    input.value = '';
    state.sending = true;
    var sendBtn = document.getElementById('cf-ai-send');
    if (sendBtn) sendBtn.disabled = true;

    // Remove chips
    var chipsEl = document.getElementById('cf-ai-messages');
    if (chipsEl) {
      var chips = chipsEl.querySelector('.cf-ai-chips');
      if (chips) chips.remove();
    }

    // Show user message
    appendMessage('user', msg);
    state.history.push({ role: 'user', content: msg });

    // Show typing
    showTyping();

    // Get cart context
    var context = {
      currentPage: window.location.pathname,
      preferences: state.preferences,
    };

    console.log('[CraftForge]   Fetching cart context...');

    // Fetch cart total, then call backend
    fetch('/cart.js')
      .then(function (r) { return r.json(); })
      .then(function (cart) {
        context.cartTotal = cart.total_price;
        console.log('[CraftForge]   Cart total:', cart.total_price);
      })
      .catch(function (err) {
        console.log('[CraftForge]   Cart fetch failed (non-Shopify page?):', err.message);
      })
      .then(function () {
        // Use .then() instead of .finally() for broader compatibility
        callBackend(msg, context);
      });
  }

  function callBackend(msg, context) {
    var url = WORKER_URL + '/chat';
    var payload = {
      message: msg,
      history: state.history.slice(-20),
      sessionId: state.sessionId,
      context: context,
    };

    console.log('[CraftForge] callBackend() → POST', url);
    console.log('[CraftForge]   Payload:', JSON.stringify(payload).substring(0, 200) + '...');

    fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    .then(function (r) {
      console.log('[CraftForge]   Response status:', r.status);
      if (!r.ok) {
        throw new Error('HTTP ' + r.status + ' ' + r.statusText);
      }
      return r.json();
    })
    .then(function (data) {
      console.log('[CraftForge]   Response data type:', data.type);
      console.log('[CraftForge]   Response content length:', (data.content || '').length);
      console.log('[CraftForge]   Actions:', JSON.stringify(data.actions || []));

      hideTyping();

      if (data.type === 'error') {
        appendMessage('assistant', data.message || 'Sorry, something went wrong. Please try again!');
        return;
      }

      appendMessage('assistant', data.content);
      state.history.push({ role: 'assistant', content: data.content });

      if (data.products && data.products.length > 0) {
        var pcontainer = document.getElementById('cf-ai-messages');
        if (pcontainer) {
          var productsDiv = document.createElement('div');
          productsDiv.className = 'cf-ai-products';
          data.products.forEach(function(p) {
            productsDiv.appendChild(createProductCard({
              handle: p.handle,
              title: p.title,
              price: p.price,
              compare_at: p.compare_at_price,
              image: p.image,
              scale: p.scale,
              rationale: '',
            }));
          });
          pcontainer.appendChild(productsDiv);
          showChips(getPostProductChips());
          scrollToBottom();
        }
      }

      if (data.actions && data.actions.length > 0) {
        data.actions.forEach(function (action) {
          if (action.action === 'add_to_cart') {
            addToCart(action.handle, null, action.quantity || 1);
          } else if (action.action === 'apply_discount') {
            try { localStorage.setItem('cf_discount', action.code); } catch (e) {}
          }
        });
      }

      extractPreferences(msg);
      saveSession();
    })
    .catch(function (err) {
      console.error('[CraftForge]   Fetch error:', err.message, err);
      hideTyping();
      appendMessage('assistant', 'Connection issue — please try again in a moment. (Error: ' + err.message + ')');
    })
    .then(function () {
      // Use .then() instead of .finally() for broader compatibility
      state.sending = false;
      var sendBtn = document.getElementById('cf-ai-send');
      if (sendBtn) sendBtn.disabled = false;
      console.log('[CraftForge]   Send complete, state.sending = false');
    });
  }

  // ── Cart ──
  function addToCart(handle, btnEl, qty) {
    console.log('[CraftForge] addToCart:', handle, 'qty:', qty || 1);
    fetch('/products/' + handle + '.js')
      .then(function (r) { return r.json(); })
      .then(function (product) {
        var variantId = product.variants[0].id;
        return fetch('/cart/add.js', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ id: variantId, quantity: qty || 1 }),
        });
      })
      .then(function (r) { return r.json(); })
      .then(function () {
        if (btnEl) {
          btnEl.textContent = 'Added!';
          btnEl.style.background = '#22c55e';
          setTimeout(function () {
            btnEl.textContent = 'Quick Add';
            btnEl.style.background = '';
          }, 2000);
        }
        showCartConfirmation(handle);
        if (window.openCartDrawer) {
          setTimeout(function () { window.openCartDrawer(); }, 500);
        }
        showChips(getPostCartChips());
      })
      .catch(function (err) {
        console.error('[CraftForge] addToCart error:', err);
        if (btnEl) { btnEl.textContent = 'Error'; }
      });
  }

  function showCartConfirmation(handle) {
    var container = document.getElementById('cf-ai-messages');
    if (!container) return;
    var div = document.createElement('div');
    div.className = 'cf-ai-cart-confirm';
    div.innerHTML = [
      '<p class="cf-ai-cart-confirm__text">✓ Added to cart!</p>',
      '<div class="cf-ai-cart-confirm__btns">',
      '  <button type="button" class="cf-ai-cart-confirm__btn cf-ai-cart-confirm__btn--cart" onclick="if(window.openCartDrawer)window.openCartDrawer()">View Cart</button>',
      '  <button type="button" class="cf-ai-cart-confirm__btn cf-ai-cart-confirm__btn--continue">Continue</button>',
      '</div>',
    ].join('');
    container.appendChild(div);
    div.querySelector('.cf-ai-cart-confirm__btn--continue').addEventListener('click', function () {
      div.remove();
    });
    scrollToBottom();
  }

  // ── Preferences ──
  function extractPreferences(msg) {
    var lower = msg.toLowerCase();
    var scaleMatch = lower.match(/(1\/\d+|\d+mm)/);
    if (scaleMatch) { state.preferences.lastScale = scaleMatch[1]; savePrefs(); }
    var themes = { wwii: /ww2|wwii|world war/, fantasy: /fantasy|dragon|knight/, scifi: /sci-?fi|cyber|space/, anime: /anime|manga/, historical: /roman|viking|samurai/ };
    for (var k in themes) {
      if (themes[k].test(lower)) { state.preferences.lastTheme = k; savePrefs(); break; }
    }
  }

  // ── Reset ──
  function resetConversation() {
    console.log('[CraftForge] Conversation reset');
    state.history = [];
    state.sessionId = generateId();
    saveSession();
    var container = document.getElementById('cf-ai-messages');
    if (container) container.innerHTML = '';
    showWelcome();
  }

  // ── Idle nudge ──
  var idleTimer;
  function resetIdleTimer() {
    clearTimeout(idleTimer);
    if (state.open && state.history.length >= 4 && !state.sending) {
      idleTimer = setTimeout(function () {
        if (!state.sending) {
          appendMessage('assistant', 'Still browsing? Want me to narrow things down or show different options?');
        }
      }, 30000);
    }
  }
  document.addEventListener('mousemove', resetIdleTimer);
  document.addEventListener('keydown', resetIdleTimer);

  console.log('[CraftForge] Widget fully initialized. Session:', state.sessionId);

})();
