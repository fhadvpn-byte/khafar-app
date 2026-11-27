"""بوابة طباعة آمنة لـ iOS Safari داخل صفحة Streamlit الأب.

تمنع طباعة واجهة التطبيق (شريط البحث الأخضر / نص أبيض على خلفية بيضاء)
عبر حقن #khafar-print-portal في window.parent ثم استدعاء parent.print().
"""
from __future__ import annotations

import re

PORTAL_ID = "khafar-print-portal"
PORTAL_CSS_ID = "khafar-print-portal-css"

# قواعد إلزامية — تُحقن في head الصفحة الأب
KHAFAR_PRINT_PORTAL_CSS = """
@media screen {
  #khafar-print-portal {
    display: none !important;
  }
}
@media print {
  @page { size: A4 portrait; margin: 5mm; }
  html, body {
    margin: 0 !important;
    padding: 0 !important;
    width: 100% !important;
    height: auto !important;
    min-height: 0 !important;
    background: #ffffff !important;
    overflow: visible !important;
    -webkit-print-color-adjust: exact !important;
    print-color-adjust: exact !important;
  }
  body > *:not(#khafar-print-portal) {
    display: none !important;
    visibility: hidden !important;
    height: 0 !important;
    max-height: 0 !important;
    overflow: hidden !important;
  }
  #khafar-print-portal {
    display: block !important;
    visibility: visible !important;
    position: static !important;
    width: 100% !important;
    margin: 0 !important;
    padding: 0 !important;
    background: #ffffff !important;
    direction: rtl !important;
  }
  #khafar-print-portal,
  #khafar-print-portal td,
  #khafar-print-portal th,
  #khafar-print-portal div,
  #khafar-print-portal span,
  #khafar-print-portal p {
    color: #111111 !important;
    -webkit-text-fill-color: #111111 !important;
    text-shadow: none !important;
    opacity: 1 !important;
  }
  #khafar-print-portal .report-main-title,
  #khafar-print-portal .red-title {
    color: #a61c1c !important;
    -webkit-text-fill-color: #a61c1c !important;
  }
  #khafar-print-portal .shaded {
    background-color: #f2f3f5 !important;
  }
  #khafar-print-portal img {
    -webkit-print-color-adjust: exact !important;
    print-color-adjust: exact !important;
    max-width: 100% !important;
  }
  #khafar-print-portal .no-print,
  #khafar-print-portal .toolbar,
  #khafar-print-portal .zoom-bar {
    display: none !important;
  }
}
"""

# سكربت يعمل داخل components.html / iframe المعاينة
KHAFAR_PRINT_PORTAL_JS = r"""
(function(){
  if (window.__khafarPrintPortalInstalled) return;
  window.__khafarPrintPortalInstalled = true;

  var PORTAL_ID = "khafar-print-portal";
  var CSS_ID = "khafar-print-portal-css";
  var PORTAL_CSS = __KHAFAR_PORTAL_CSS_JSON__;

  function getParentDoc(){
    try {
      if (window.parent && window.parent !== window && window.parent.document && window.parent.document.body)
        return { win: window.parent, doc: window.parent.document };
    } catch (e0) {}
    try {
      if (window.top && window.top !== window && window.top.document && window.top.document.body)
        return { win: window.top, doc: window.top.document };
    } catch (e1) {}
    return null;
  }

  function scopeSelector(sel, scope){
    sel = String(sel || "").trim();
    if (!sel) return sel;
    if (sel.indexOf(scope) === 0) return sel;
    if (sel === "html" || sel === "body" || sel === ":root") return scope;
    return scope + " " + sel;
  }

  function scopeRuleList(rules, scope, out){
    if (!rules) return;
    for (var i = 0; i < rules.length; i++) {
      var rule = rules[i];
      try {
        if (rule.type === CSSRule.IMPORT_RULE || rule.type === CSSRule.FONT_FACE_RULE || rule.type === CSSRule.PAGE_RULE || rule.type === CSSRule.KEYFRAMES_RULE) {
          out.push(rule.cssText);
        } else if (rule.type === CSSRule.MEDIA_RULE) {
          var inner = [];
          scopeRuleList(rule.cssRules, scope, inner);
          out.push("@media " + rule.conditionText + "{" + inner.join("\n") + "}");
        } else if (rule.type === CSSRule.SUPPORTS_RULE) {
          var inner2 = [];
          scopeRuleList(rule.cssRules, scope, inner2);
          out.push("@supports " + rule.conditionText + "{" + inner2.join("\n") + "}");
        } else if (rule.type === CSSRule.STYLE_RULE) {
          var sels = rule.selectorText.split(",").map(function(s){ return scopeSelector(s, scope); }).join(", ");
          out.push(sels + "{" + rule.style.cssText + "}");
        }
      } catch (eR) {}
    }
  }

  function collectScopedCss(scope){
    var out = [];
    Array.prototype.forEach.call(document.styleSheets || [], function(sheet){
      var rules;
      try { rules = sheet.cssRules; } catch (e) { return; }
      if (!rules) return;
      scopeRuleList(rules, scope, out);
    });
    return out.join("\n");
  }

  function pickPrintRoot(){
    return document.querySelector(".a4-sheet, .a4-page, .a4-paper, #a4Sheet, .a4, .a4-page-frame, .report-container, .print-area")
      || document.body;
  }

  function buildPortalInnerHtml(){
    var root = pickPrintRoot();
    var clone = root.cloneNode(true);
    try {
      clone.querySelectorAll(".no-print, .toolbar, .zoom-bar, #zoomBar, script").forEach(function(n){ n.remove(); });
    } catch (eC) {}
    // مزامنة مصادر الصور الحية
    try {
      var liveImgs = root.querySelectorAll("img");
      var cloneImgs = clone.querySelectorAll("img");
      for (var i = 0; i < liveImgs.length && i < cloneImgs.length; i++) {
        var src = liveImgs[i].getAttribute("src");
        if (src) cloneImgs[i].setAttribute("src", src);
      }
    } catch (eI) {}
    return clone.outerHTML;
  }

  function ensurePortalCss(doc, reportCss){
    var el = doc.getElementById(CSS_ID);
    if (!el) {
      el = doc.createElement("style");
      el.id = CSS_ID;
      (doc.head || doc.documentElement).appendChild(el);
    }
    el.textContent = PORTAL_CSS + "\n" + (reportCss || "");
  }

  function syncPortalFromHtmlString(fullHtml){
    var parent = getParentDoc();
    if (!parent) return false;
    var doc = parent.doc;
    var tmp = doc.implementation.createHTMLDocument("print");
    tmp.documentElement.innerHTML = String(fullHtml || "");
    // إن وُجدت وثيقة كاملة استخرج الجسم والأنماط
    var styles = "";
    Array.prototype.forEach.call(tmp.querySelectorAll("style"), function(s){ styles += s.textContent + "\n"; });
    var bodyRoot = tmp.querySelector(".a4-sheet, .a4-page, .a4-paper, #a4Sheet, .a4-page-frame, .report-container, .print-area")
      || tmp.body;
    var inner = bodyRoot ? bodyRoot.outerHTML : String(fullHtml || "");
    var scoped = "";
    try {
      // أعد تحليل الأنماط عبر عنصر مؤقت في الأب
      var probe = doc.createElement("style");
      probe.textContent = styles;
      doc.documentElement.appendChild(probe);
      var collected = [];
      try { scopeRuleList(probe.sheet && probe.sheet.cssRules, "#" + PORTAL_ID, collected); } catch (eS) {}
      probe.remove();
      scoped = collected.join("\n");
    } catch (e2) {
      scoped = "";
    }
    ensurePortalCss(doc, scoped);
    var portal = doc.getElementById(PORTAL_ID);
    if (!portal) {
      portal = doc.createElement("div");
      portal.id = PORTAL_ID;
      doc.body.appendChild(portal);
    }
    portal.setAttribute("dir", "rtl");
    portal.innerHTML = inner;
    return true;
  }

  function syncPortal(){
    var parent = getParentDoc();
    if (!parent) return false;
    var doc = parent.doc;
    var reportCss = collectScopedCss("#" + PORTAL_ID);
    ensurePortalCss(doc, reportCss);
    var portal = doc.getElementById(PORTAL_ID);
    if (!portal) {
      portal = doc.createElement("div");
      portal.id = PORTAL_ID;
      doc.body.appendChild(portal);
    }
    portal.setAttribute("dir", "rtl");
    portal.innerHTML = buildPortalInnerHtml();
    return true;
  }

  function openPopupWithHtml(htmlDoc){
    try {
      var printWin = window.open("", "_blank");
      if (!printWin || printWin.closed) return false;
      printWin.document.open();
      printWin.document.write(htmlDoc);
      printWin.document.close();
      return true;
    } catch (e) {
      return false;
    }
  }

  function buildStandaloneDoc(){
    var styles = "";
    Array.prototype.forEach.call(document.querySelectorAll("style"), function(s){
      styles += s.outerHTML;
    });
    return "<!DOCTYPE html><html lang=\"ar\" dir=\"rtl\"><head><meta charset=\"utf-8\">"
      + "<meta name=\"viewport\" content=\"width=794\">"
      + styles
      + "</head><body style=\"margin:0;background:#fff;color:#111;\">"
      + buildPortalInnerHtml()
      + "</body></html>";
  }

  function khafarPortalPrint(ev){
    if (ev && ev.preventDefault) ev.preventDefault();
    if (ev && ev.stopPropagation) ev.stopPropagation();
    // منع الطباعة المزدوجة إذا وُجد onclick + مستمع
    var now = Date.now();
    if (window.__khafarPortalPrintAt && (now - window.__khafarPortalPrintAt) < 1200) return false;
    window.__khafarPortalPrintAt = now;
    var synced = false;
    try { synced = syncPortal(); } catch (e0) { synced = false; }

    if (synced) {
      try {
        var parent = getParentDoc();
        if (parent && parent.win) {
          try { parent.win.focus(); } catch (eF) {}
          parent.win.print();
          return false;
        }
      } catch (e1) {}
    }

    // مسار احتياطي: نافذة منبثقة داخل ضغطة المستخدم
    try {
      if (openPopupWithHtml(buildStandaloneDoc())) return false;
    } catch (e2) {}

    // أخيرًا: طباعة الإطار الحالي (سطح المكتب)
    try { window.focus(); } catch (e3) {}
    try { window.print(); } catch (e4) {}
    return false;
  }

  window.khafarSyncPrintPortal = syncPortal;
  window.khafarSyncPrintPortalHtml = syncPortalFromHtmlString;
  window.khafarPortalPrint = khafarPortalPrint;

  function bindButtons(){
    Array.prototype.forEach.call(document.querySelectorAll(".print-btn, #printOfficialBtn, [data-khafar-print]"), function(btn){
      if (btn.__khafarPortalBound) return;
      btn.__khafarPortalBound = true;
      btn.addEventListener("click", khafarPortalPrint, false);
    });
  }

  function boot(){
    try { syncPortal(); } catch (e) {}
    bindButtons();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
  window.addEventListener("load", function(){ try { syncPortal(); } catch (e) {} });
  // إعادة مزامنة قبل طباعة الإطار الحالي إن حصلت
  window.addEventListener("beforeprint", function(){ try { syncPortal(); } catch (e) {} });
})();
"""


def print_portal_script_tag() -> str:
    """وسم <script> جاهز للحقن داخل وثيقة المعاينة."""
    import json

    css_json = json.dumps(KHAFAR_PRINT_PORTAL_CSS)
    js = KHAFAR_PRINT_PORTAL_JS.replace("__KHAFAR_PORTAL_CSS_JSON__", css_json)
    return f"<script>\n{js}\n</script>"


def inject_print_portal(html_doc: str) -> str:
    """حقن سكربت البوابة وإعادة توجيه أزرار window.print إلى khafarPortalPrint."""
    html = str(html_doc or "")
    if not html.strip():
        return html
    # تجنّب الحقن المزدوج
    if "khafar-print-portal" in html and "__khafarPrintPortalInstalled" in html:
        return html
    html = re.sub(
        r"""onclick\s*=\s*(['"])\s*window\.print\s*\(\s*\)\s*\1""",
        'onclick="khafarPortalPrint(event)"',
        html,
        flags=re.IGNORECASE,
    )
    script = print_portal_script_tag()
    if re.search(r"</body\s*>", html, flags=re.IGNORECASE):
        return re.sub(r"</body\s*>", script + "</body>", html, count=1, flags=re.IGNORECASE)
    return html + script


def portal_print_fallback_js() -> str:
    """مقتطف قصير لاستدعاء البوابة من مسارات الطباعة في app.py عند فشل window.open."""
    return (
        "try{"
        "if(typeof window.khafarSyncPrintPortalHtml==='function'){window.khafarSyncPrintPortalHtml(arguments[0]);}"
        "else if(typeof window.khafarSyncPrintPortal==='function'){window.khafarSyncPrintPortal();}"
        "var __p=null;try{__p=window.parent&&window.parent!==window?window.parent:window.top;}catch(e){__p=null;}"
        "if(__p&&__p.print){try{__p.focus();}catch(e2){}__p.print();return true;}"
        "}catch(e3){}return false;"
    )
