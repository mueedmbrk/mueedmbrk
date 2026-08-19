/* =========================================================
   Mueed Mubarak — Portfolio interactions
   ========================================================= */
(function () {
  'use strict';

  var reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var $  = function (s, c) { return (c || document).querySelector(s); };
  var $$ = function (s, c) { return Array.prototype.slice.call((c || document).querySelectorAll(s)); };

  /* ---------- Year ---------- */
  var yearEl = $('#year');
  if (yearEl) yearEl.textContent = new Date().getFullYear();

  /* ---------- Sticky header + scroll progress + back-to-top ---------- */
  var header = $('#header');
  var bar    = $('#scrollBar');
  var toTop  = $('#toTop');
  var ticking = false;

  function onScroll() {
    var y = window.scrollY || window.pageYOffset;
    var max = document.documentElement.scrollHeight - window.innerHeight;

    if (header) header.classList.toggle('is-stuck', y > 12);
    if (bar) bar.style.width = (max > 0 ? (y / max) * 100 : 0) + '%';
    if (toTop) toTop.classList.toggle('is-on', y > 600);
    ticking = false;
  }
  window.addEventListener('scroll', function () {
    if (!ticking) { ticking = true; window.requestAnimationFrame(onScroll); }
  }, { passive: true });
  onScroll();

  /* ---------- Mobile menu ---------- */
  var burger = $('#burger');
  var nav    = $('#nav');

  function closeMenu() {
    if (!nav) return;
    nav.classList.remove('is-open');
    if (burger) { burger.classList.remove('is-open'); burger.setAttribute('aria-expanded', 'false'); }
    document.body.classList.remove('is-locked');
  }

  if (burger && nav) {
    burger.addEventListener('click', function () {
      var open = nav.classList.toggle('is-open');
      burger.classList.toggle('is-open', open);
      burger.setAttribute('aria-expanded', String(open));
      document.body.classList.toggle('is-locked', open);
    });
    $$('a', nav).forEach(function (a) { a.addEventListener('click', closeMenu); });
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape') closeMenu(); });
  }

  /* ---------- Reveal on scroll ---------- */
  var revealables = $$('[data-reveal]');
  if (reduced || !('IntersectionObserver' in window)) {
    revealables.forEach(function (el) { el.classList.add('is-in'); });
  } else {
    var revealIO = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        var el = entry.target;
        var delay = parseInt(el.getAttribute('data-delay') || '0', 10);
        setTimeout(function () { el.classList.add('is-in'); }, delay);
        revealIO.unobserve(el);
      });
    }, { threshold: 0.12, rootMargin: '0px 0px -8% 0px' });
    revealables.forEach(function (el) { revealIO.observe(el); });
  }

  /* ---------- Typed roles ---------- */
  var typedEl = $('#typed');
  var roles = [
    'AI Automation Engineer',
    'Machine Learning Developer',
    'Conversational AI Specialist',
    'n8n Workflow Architect',
    'AI Trainer & Mentor'
  ];
  if (typedEl) {
    if (reduced) {
      typedEl.textContent = roles[0];
    } else {
      var ri = 0, ci = 0, deleting = false;
      (function type() {
        var word = roles[ri];
        ci += deleting ? -1 : 1;
        typedEl.textContent = word.slice(0, ci);

        var wait = deleting ? 34 : 68;
        if (!deleting && ci === word.length) { deleting = true; wait = 1700; }
        else if (deleting && ci === 0) { deleting = false; ri = (ri + 1) % roles.length; wait = 320; }
        setTimeout(type, wait);
      })();
    }
  }

  /* ---------- Animated counters ---------- */
  var counters = $$('.count');
  function runCount(el) {
    var target = parseInt(el.getAttribute('data-count'), 10) || 0;
    if (reduced) { el.textContent = String(target); return; }
    var dur = 1500, start = null;
    function step(ts) {
      if (start === null) start = ts;
      var p = Math.min((ts - start) / dur, 1);
      var eased = 1 - Math.pow(1 - p, 3);
      el.textContent = String(Math.round(target * eased));
      if (p < 1) window.requestAnimationFrame(step);
    }
    window.requestAnimationFrame(step);
  }
  if ('IntersectionObserver' in window) {
    var countIO = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) { runCount(e.target); countIO.unobserve(e.target); }
      });
    }, { threshold: 0.6 });
    counters.forEach(function (el) { countIO.observe(el); });
  } else {
    counters.forEach(runCount);
  }

  /* ---------- Skill bars ---------- */
  var barFills = $$('.bar__track i');
  function fill(el) { el.style.width = (el.getAttribute('data-w') || 0) + '%'; }
  if ('IntersectionObserver' in window) {
    var barIO = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) { fill(e.target); barIO.unobserve(e.target); }
      });
    }, { threshold: 0.4 });
    barFills.forEach(function (el) { barIO.observe(el); });
  } else {
    barFills.forEach(fill);
  }

  /* ---------- Scroll spy + nav pill ---------- */
  var navLinks = $$('#nav a');
  var pill = $('.nav__pill');
  var sections = navLinks
    .map(function (a) {
      var href = a.getAttribute('href') || '';
      return href.charAt(0) === '#' ? document.querySelector(href) : null;
    })
    .filter(Boolean);

  function movePill(link) {
    if (!pill || !link || window.innerWidth <= 860) return;
    pill.style.width = link.offsetWidth + 'px';
    pill.style.transform = 'translate(' + link.offsetLeft + 'px,-50%)';
    pill.style.opacity = '1';
  }

  function setActive(id) {
    var current = null;
    navLinks.forEach(function (a) {
      var on = a.getAttribute('href') === '#' + id;
      a.classList.toggle('is-active', on);
      if (on) current = a;
    });
    if (current) movePill(current);
  }

  if (sections.length && 'IntersectionObserver' in window) {
    var spyIO = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) { if (e.isIntersecting) setActive(e.target.id); });
    }, { rootMargin: '-45% 0px -50% 0px', threshold: 0 });
    sections.forEach(function (s) { spyIO.observe(s); });
  }
  navLinks.forEach(function (a) {
    a.addEventListener('mouseenter', function () { movePill(a); });
  });
  if (nav) {
    nav.addEventListener('mouseleave', function () {
      var active = $('#nav a.is-active');
      if (active) movePill(active); else if (pill) pill.style.opacity = '0';
    });
  }
  window.addEventListener('resize', function () {
    var active = $('#nav a.is-active');
    if (active) movePill(active);
  });

  /* ---------- Magnetic buttons ---------- */
  if (!reduced && window.matchMedia('(hover: hover) and (pointer: fine)').matches) {
    $$('[data-magnetic]').forEach(function (el) {
      el.addEventListener('mousemove', function (e) {
        var r = el.getBoundingClientRect();
        var mx = e.clientX - r.left - r.width / 2;
        var my = e.clientY - r.top - r.height / 2;
        el.style.transform = 'translate(' + mx * 0.18 + 'px,' + (my * 0.28 - 2) + 'px)';
      });
      el.addEventListener('mouseleave', function () { el.style.transform = ''; });
    });
  }

  /* ---------- Card spotlight ---------- */
  $$('.card, .proj').forEach(function (card) {
    card.addEventListener('pointermove', function (e) {
      var r = card.getBoundingClientRect();
      card.style.setProperty('--mx', (e.clientX - r.left) + 'px');
      card.style.setProperty('--my', (e.clientY - r.top) + 'px');
    });
  });

  /* ---------- Project filters ---------- */
  var filters = $$('.filter');
  var projects = $$('#projectGrid .proj');
  filters.forEach(function (btn) {
    btn.addEventListener('click', function () {
      var f = btn.getAttribute('data-filter');
      filters.forEach(function (b) {
        var on = b === btn;
        b.classList.toggle('is-active', on);
        b.setAttribute('aria-selected', String(on));
      });
      projects.forEach(function (p) {
        var cats = (p.getAttribute('data-cat') || '').split(/\s+/);
        var show = f === 'all' || cats.indexOf(f) !== -1;
        p.classList.toggle('is-hidden', !show);
        if (show && !reduced) {
          p.style.animation = 'none';
          /* force reflow so the animation restarts */
          void p.offsetWidth;
          p.style.animation = 'popIn .5s cubic-bezier(.22,1,.36,1) both';
        }
      });
    });
  });

  /* ---------- Portrait parallax ---------- */
  var portrait = $('#portrait');
  var portraitImg = $('.portrait__img');
  if (portrait && portraitImg && !reduced && window.matchMedia('(hover: hover) and (pointer: fine)').matches) {
    portrait.addEventListener('mousemove', function (e) {
      var r = portrait.getBoundingClientRect();
      var px = (e.clientX - r.left) / r.width - 0.5;
      var py = (e.clientY - r.top) / r.height - 0.5;
      portraitImg.style.transform =
        'perspective(900px) rotateY(' + px * 9 + 'deg) rotateX(' + (-py * 7) + 'deg) translateZ(18px)';
      portraitImg.style.animationPlayState = 'paused';
    });
    portrait.addEventListener('mouseleave', function () {
      portraitImg.style.transform = '';
      portraitImg.style.animationPlayState = '';
    });
  }

  /* ---------- Card tilt ---------- */
  if (!reduced && window.matchMedia('(hover: hover) and (pointer: fine)').matches) {
    $$('[data-tilt]').forEach(function (el) {
      el.addEventListener('pointermove', function (e) {
        var r = el.getBoundingClientRect();
        var px = (e.clientX - r.left) / r.width - 0.5;
        var py = (e.clientY - r.top) / r.height - 0.5;
        el.style.transform =
          'perspective(800px) rotateY(' + px * 5 + 'deg) rotateX(' + (-py * 5) + 'deg) translateY(-6px)';
      });
      el.addEventListener('pointerleave', function () { el.style.transform = ''; });
    });
  }

  /* ---------- n8n flow: travelling pulse + node highlight ---------- */
  var flow = $('.flow');
  if (flow && !reduced) {
    var pulse = $('.flow__pulse', flow);
    var wires = $$('.flow__wires path', flow);
    var nodes = $$('.fnode', flow);
    var order = [[0, 1], [1, 2], [2, 3], [2, 4], [2, 5]];
    var leg = 0, t = 0, playing = false;

    function light(i) {
      nodes.forEach(function (n, idx) { n.classList.toggle('is-lit', idx === i); });
    }

    function frame() {
      if (!playing) return;
      var path = wires[leg];
      if (!path) { leg = 0; window.requestAnimationFrame(frame); return; }
      var len = path.getTotalLength();
      t += 0.014;
      if (t >= 1) {
        t = 0;
        light(order[leg][1]);
        leg = (leg + 1) % wires.length;
        if (leg === 0) setTimeout(function () { window.requestAnimationFrame(frame); }, 500);
        else window.requestAnimationFrame(frame);
        return;
      }
      var pt = path.getPointAtLength(len * t);
      pulse.setAttribute('cx', pt.x);
      pulse.setAttribute('cy', pt.y);
      pulse.style.opacity = '1';
      if (t < 0.06) light(order[leg][0]);
      window.requestAnimationFrame(frame);
    }

    if ('IntersectionObserver' in window) {
      var flowIO = new IntersectionObserver(function (entries) {
        entries.forEach(function (e) {
          playing = e.isIntersecting;
          if (playing) window.requestAnimationFrame(frame);
        });
      }, { threshold: 0.25 });
      flowIO.observe(flow);
    } else {
      playing = true;
      window.requestAnimationFrame(frame);
    }
  }

  /* ---------- Anchor offset for fixed header ---------- */
  $$('a[href^="#"]').forEach(function (a) {
    a.addEventListener('click', function (e) {
      var id = a.getAttribute('href');
      if (!id || id === '#') return;
      var target = document.querySelector(id);
      if (!target) return;
      e.preventDefault();
      var top = target.getBoundingClientRect().top + window.scrollY - (id === '#hero' ? 0 : 74);
      window.scrollTo({ top: top, behavior: reduced ? 'auto' : 'smooth' });
      history.replaceState(null, '', id);
    });
  });
})();
