/**
 * CraftForge AI — Chat widget for Shopify storefronts.
 * Vanilla JS, no dependencies. Communicates with Cloudflare Worker backend.
 */
(function () {
  'use strict';

  var CONFIG = window.CRAFTFORGE_CONFIG || {};
  var WORKER_URL = CONFIG.workerUrl || '';
  var STORE_URL = CONFIG.storeUrl || '';
  var SESSION_KEY = 'craftforge_session';
  var PREFS_KEY = 'craftforge_prefs';

  if (!WORKER_URL) {
    console.warn('CraftForge AI: No workerUrl configured');
    return;
  }

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
        history: state.history.slice(-40), // Keep last 20 turns
        sessionId: state.sessionId,
      }));
    } catch (e) {}
  }

  function savePrefs() {
    try { localStorage.setItem(PREFS_KEY, JSON.stringify(state.preferences)); } catch (e) {}
  }

  // ── DOM ──
  function createWidget() {
    // Bubble
    var bubble = document.createElement('button');
    bubble.className = 'cf-ai-bubble' + (state.history.length === 0 ? ' cf-ai-bubble--pulse' : '');
    bubble.setAttribute('aria-label', 'Open CraftForge AI assistant');
    bubble.innerHTML = '<svg viewBox="0 0 24 24"><path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm0 14H5.17L4 17.17V4h16v12z"/><path d="M7 9h2v2H7zm4 0h2v2h-2zm4 0h2v2h-2z"/></svg>';
    bubble.addEventListener('click', togglePanel);

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
      '    <button class="cf-ai-header__btn" id="cf-ai-reset" title="Start over">↻</button>',
      '    <button class="cf-ai-header__btn" id="cf-ai-close" title="Close">✕</button>',
      '  </div>',
      '</div>',
      '<div class="cf-ai-messages" id="cf-ai-messages"></div>',
      '<div class="cf-ai-input">',
      '  <input type="text" class="cf-ai-input__field" id="cf-ai-input" placeholder="Ask me anything about resin models..." autocomplete="off">',
      '  <button class="cf-ai-input__send" id="cf-ai-send" aria-label="Send">',
      '    <svg viewBox="0 0 24 24"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>',
      '  </button>',
      '</div>',
    ].join('\n');

    document.body.appendChild(bubble);
    document.body.appendChild(panel);

    // Bind events
    document.getElementById('cf-ai-close').addEventListener('click', togglePanel);
    document.getElementById('cf-ai-reset').addEventListener('click', resetConversation);
    document.getElementById('cf-ai-send').addEventListener('click', sendMessage);
    document.getElementById('cf-ai-input').addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
    });

    // Render existing history
    if (state.history.length > 0) {
      state.history.forEach(function (msg) {
        appendMessage(msg.role, msg.content, true);
      });
    }

    return { bubble: bubble, panel: panel };
  }

  var dom = createWidget();

  // ── Panel toggle ──
  function togglePanel() {
    state.open = !state.open;
    dom.panel.classList.toggle('cf-ai-panel--open', state.open);
    dom.bubble.classList.toggle('cf-ai-bubble--hidden', state.open);

    if (state.open) {
      // Show welcome if first time
      if (state.history.length === 0) {
        showWelcome();
      }
      setTimeout(function () {
        document.getElementById('cf-ai-input').focus();
      }, 300);
      scrollToBottom();
    }
  }

  function showWelcome() {
    // Check for return visitor
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

    // Quick chips
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
    var div = document.createElement('div');
    div.className = 'cf-ai-msg cf-ai-msg--' + (role === 'user' ? 'user' : 'bot');

    // Parse product cards from content
    var parsed = parseProductCards(content);
    div.innerHTML = parsed.html;
    container.appendChild(div);

    // Render product cards
    if (parsed.products.length > 0) {
      var productsDiv = document.createElement('div');
      productsDiv.className = 'cf-ai-products';
      parsed.products.forEach(function (p) {
        productsDiv.appendChild(createProductCard(p));
      });
      container.appendChild(productsDiv);

      // Show post-product chips
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

    // Remove product card tags from display text
    var html = content.replace(/<product-card[^>]*\/>/g, '');
    // Convert markdown bold
    html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    // Convert newlines
    html = html.replace(/\n/g, '<br>');

    return { html: html, products: products };
  }

  function createProductCard(p) {
    var card = document.createElement('div');
    card.className = 'cf-ai-product';

    var savings = '';
    if (p.compare_at && parseFloat(p.compare_at) > parseFloat(p.price)) {
      var pct = Math.round((1 - parseFloat(p.price) / parseFloat(p.compare_at)) * 100);
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
      '    <button class="cf-ai-product__btn cf-ai-product__btn--add" data-handle="' + (p.handle || '') + '">Quick Add</button>',
      '    <a href="/products/' + (p.handle || '') + '" target="_blank" class="cf-ai-product__btn cf-ai-product__btn--view">View</a>',
      '  </div>',
      '</div>',
    ].join('\n');

    // Bind Quick Add
    card.querySelector('.cf-ai-product__btn--add').addEventListener('click', function () {
      addToCart(p.handle, this);
    });

    return card;
  }

  function showChips(chips) {
    var container = document.getElementById('cf-ai-messages');
    // Remove existing chips
    var old = container.querySelector('.cf-ai-chips');
    if (old) old.remove();

    var div = document.createElement('div');
    div.className = 'cf-ai-chips';
    chips.forEach(function (chip) {
      var btn = document.createElement('button');
      btn.className = 'cf-ai-chip';
      btn.textContent = chip.label;
      btn.addEventListener('click', function () {
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
    setTimeout(function () { container.scrollTop = container.scrollHeight; }, 50);
  }

  // ── Send ──
  function sendMessage() {
    if (state.sending) return;
    var input = document.getElementById('cf-ai-input');
    var msg = input.value.trim();
    if (!msg) return;

    input.value = '';
    state.sending = true;
    document.getElementById('cf-ai-send').disabled = true;

    // Remove chips
    var chips = document.querySelector('.cf-ai-chips');
    if (chips) chips.remove();

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

    // Fetch cart total
    fetch('/cart.js')
      .then(function (r) { return r.json(); })
      .then(function (cart) { context.cartTotal = cart.total_price; })
      .catch(function () {})
      .finally(function () {
        callBackend(msg, context);
      });
  }

  function callBackend(msg, context) {
    fetch(WORKER_URL + '/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message: msg,
        history: state.history.slice(-20), // Send last 10 turns
        sessionId: state.sessionId,
        context: context,
      }),
    })
    .then(function (r) { return r.json(); })
    .then(function (data) {
      hideTyping();

      if (data.type === 'error') {
        appendMessage('assistant', 'Sorry, something went wrong. Please try again!');
        return;
      }

      // Show response
      appendMessage('assistant', data.content);
      state.history.push({ role: 'assistant', content: data.content });

      // Handle side-effect actions
      if (data.actions && data.actions.length > 0) {
        data.actions.forEach(function (action) {
          if (action.action === 'add_to_cart') {
            addToCart(action.handle, null, action.quantity || 1);
          } else if (action.action === 'apply_discount') {
            // Store discount code for checkout
            try { localStorage.setItem('cf_discount', action.code); } catch (e) {}
          }
        });
      }

      // Extract preferences from conversation
      extractPreferences(msg);
      saveSession();
    })
    .catch(function (err) {
      hideTyping();
      appendMessage('assistant', 'Connection issue — please try again in a moment.');
    })
    .finally(function () {
      state.sending = false;
      document.getElementById('cf-ai-send').disabled = false;
    });
  }

  // ── Cart ──
  function addToCart(handle, btnEl, qty) {
    // First get the variant ID
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
        // Update button
        if (btnEl) {
          btnEl.textContent = 'Added!';
          btnEl.style.background = '#22c55e';
          setTimeout(function () {
            btnEl.textContent = 'Quick Add';
            btnEl.style.background = '';
          }, 2000);
        }

        // Show cart confirmation in chat
        showCartConfirmation(handle);

        // Open cart drawer if available
        if (window.openCartDrawer) {
          setTimeout(function () { window.openCartDrawer(); }, 500);
        }

        // Show post-cart chips
        showChips(getPostCartChips());
      })
      .catch(function () {
        if (btnEl) { btnEl.textContent = 'Error'; }
      });
  }

  function showCartConfirmation(handle) {
    var container = document.getElementById('cf-ai-messages');
    var div = document.createElement('div');
    div.className = 'cf-ai-cart-confirm';
    div.innerHTML = [
      '<p class="cf-ai-cart-confirm__text">✓ Added to cart!</p>',
      '<div class="cf-ai-cart-confirm__btns">',
      '  <button class="cf-ai-cart-confirm__btn cf-ai-cart-confirm__btn--cart" onclick="if(window.openCartDrawer)window.openCartDrawer()">View Cart</button>',
      '  <button class="cf-ai-cart-confirm__btn cf-ai-cart-confirm__btn--continue">Continue</button>',
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
    // Scale
    var scaleMatch = lower.match(/(1\/\d+|\d+mm)/);
    if (scaleMatch) { state.preferences.lastScale = scaleMatch[1]; savePrefs(); }
    // Theme
    var themes = { wwii: /ww2|wwii|world war/, fantasy: /fantasy|dragon|knight/, scifi: /sci-?fi|cyber|space/, anime: /anime|manga/, historical: /roman|viking|samurai/ };
    for (var k in themes) {
      if (themes[k].test(lower)) { state.preferences.lastTheme = k; savePrefs(); break; }
    }
  }

  // ── Reset ──
  function resetConversation() {
    state.history = [];
    state.sessionId = generateId();
    saveSession();
    document.getElementById('cf-ai-messages').innerHTML = '';
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

})();
