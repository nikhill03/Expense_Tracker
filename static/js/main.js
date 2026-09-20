// Bahi-Khata — progressive enhancement only.
//
// Every page works with this file blocked: forms submit, links navigate, the
// theme still follows the OS. What's here makes those things nicer.

(function () {
  'use strict';

  var root = document.documentElement;

  // ---------------------------------------------------------------- //
  // Theme                                                             //
  // ---------------------------------------------------------------- //
  // The inline script in base.html has already stamped data-theme before
  // paint. This only wires up the toggle and keeps an un-chosen theme
  // following the OS if it changes while the page is open.

  function syncToggle() {
    var btn = document.getElementById('theme-toggle');
    if (!btn) return;
    var dark = root.dataset.theme === 'dark';
    btn.setAttribute('aria-pressed', String(dark));
    btn.setAttribute('aria-label', dark ? 'Switch to light theme' : 'Switch to dark theme');
  }

  function setTheme(theme, remember) {
    root.dataset.theme = theme;
    if (remember) {
      try { localStorage.setItem('bk-theme', theme); } catch (e) { /* private mode */ }
    }
    // Keep the browser chrome in step with the page.
    document.querySelectorAll('meta[name="theme-color"]').forEach(function (meta) {
      meta.setAttribute('content', theme === 'dark' ? '#14141f' : '#fafaf8');
      meta.removeAttribute('media');
    });
    syncToggle();
  }

  var toggle = document.getElementById('theme-toggle');
  if (toggle) {
    toggle.addEventListener('click', function () {
      setTheme(root.dataset.theme === 'dark' ? 'light' : 'dark', true);
    });
    syncToggle();
  }

  try {
    var media = matchMedia('(prefers-color-scheme: dark)');
    media.addEventListener('change', function (e) {
      var chosen = null;
      try { chosen = localStorage.getItem('bk-theme'); } catch (err) { /* ignore */ }
      if (!chosen) setTheme(e.matches ? 'dark' : 'light', false);
    });
  } catch (e) { /* older Safari */ }

  // ---------------------------------------------------------------- //
  // Destructive actions                                               //
  // ---------------------------------------------------------------- //
  // A data-confirm attribute rather than an inline onsubmit, so the markup
  // stays free of script and one handler covers every delete on the page.

  document.addEventListener('submit', function (e) {
    var message = e.target.getAttribute && e.target.getAttribute('data-confirm');
    if (message && !window.confirm(message)) e.preventDefault();
  });

  // ---------------------------------------------------------------- //
  // Quick-add sheet                                                   //
  // ---------------------------------------------------------------- //

  var sheet = document.getElementById('quick-sheet');

  if (sheet) {
    // Focus the amount as the sheet opens — the keypad should be up before the
    // animation finishes.
    sheet.addEventListener('toggle', function (e) {
      if (e.newState !== 'open') return;
      var amount = sheet.querySelector('[data-quick-amount]');
      if (amount) setTimeout(function () { amount.focus(); }, 60);
    });

    // A downward drag on the grip or header should dismiss it, the way a
    // native sheet does.
    var startY = null;
    sheet.addEventListener('touchstart', function (e) {
      startY = sheet.scrollTop === 0 ? e.touches[0].clientY : null;
    }, { passive: true });

    sheet.addEventListener('touchmove', function (e) {
      if (startY === null) return;
      var dy = e.touches[0].clientY - startY;
      if (dy > 0) sheet.style.translate = '0 ' + dy + 'px';
    }, { passive: true });

    sheet.addEventListener('touchend', function () {
      if (startY === null) return;
      var dy = parseFloat(sheet.style.translate.split(' ')[1]) || 0;
      sheet.style.translate = '';
      if (dy > 110) sheet.hidePopover();
      startY = null;
    });
  }

  // Popover is widely supported now, but if it isn't, send the button to the
  // full /quick page instead of leaving it inert.
  if (!HTMLElement.prototype.hasOwnProperty('popover')) {
    document.querySelectorAll('[popovertarget="quick-sheet"]').forEach(function (btn) {
      btn.addEventListener('click', function () { location.href = '/quick'; });
    });
    if (sheet) sheet.hidden = true;
  }

  // ---------------------------------------------------------------- //
  // Quick-add form                                                    //
  // ---------------------------------------------------------------- //

  document.querySelectorAll('[data-quick-form]').forEach(function (form) {
    var dateInput = form.querySelector('[data-quick-date]');
    var dateLabel = form.querySelector('[data-quick-datelabel]');
    var submit = form.querySelector('[data-quick-submit]');
    var amount = form.querySelector('[data-quick-amount]');

    // Say which date is actually selected, so a row that reads as a sentence is
    // never a lie. The server renders this too; this keeps it right after the
    // user picks something.
    function describeDate() {
      if (!dateInput || !dateLabel || !dateInput.value) return;
      // Read today off the max attribute the server stamped. new Date() would
      // be the browser's clock and toISOString() would be UTC — either one
      // reintroduces the timezone bug this app just fixed server-side.
      var today = (dateInput.getAttribute('max') || '').slice(0, 10);
      if (dateInput.value === today) {
        dateLabel.textContent = 'Dated today';
        return;
      }
      var d = new Date(dateInput.value + 'T00:00:00');
      dateLabel.textContent = 'Dated ' + d.toLocaleDateString(undefined, {
        day: 'numeric', month: 'short'
      });
    }

    if (dateInput) {
      dateInput.addEventListener('change', describeDate);
      dateInput.addEventListener('input', describeDate);
      describeDate();

      // On a phone, tapping the transparent input already opened the picker.
      // Desktop Chrome only opens it from the calendar glyph, which this row
      // deliberately covers — so the row would look inert without this.
      if (dateInput.showPicker) {
        dateInput.addEventListener('click', function () {
          try { dateInput.showPicker(); } catch (e) { /* already open */ }
        });
      }
    }

    // Mirror the amount into the button, so the last thing you read before
    // tapping is what you are about to save.
    function describeAmount() {
      if (!amount || !submit) return;
      var value = parseFloat(amount.value);
      submit.textContent = value > 0
        ? 'Save ₹' + value.toLocaleString('en-IN', { maximumFractionDigits: 2 })
        : 'Save expense';
    }

    if (amount) {
      amount.addEventListener('input', describeAmount);
      describeAmount();
    }

    // Guard against a double-tap posting the same expense twice.
    form.addEventListener('submit', function () {
      if (!form.checkValidity() || !submit) return;
      submit.disabled = true;
      submit.textContent = 'Saving…';
      // Re-enable if the page is restored from the back/forward cache.
      setTimeout(function () { submit.disabled = false; describeAmount(); }, 4000);
    });
  });

  window.addEventListener('pageshow', function (e) {
    if (!e.persisted) return;
    document.querySelectorAll('[data-quick-submit]').forEach(function (b) { b.disabled = false; });
  });
}());
