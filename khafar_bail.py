import copy, inspect, re
import streamlit as st
import streamlit.components.v1 as comp
from streamlit.delta_generator import DeltaGenerator as DG

_KHAFAR_BAIL_VER = "v6"
BAIL_ID = "decl_accident_bail"
BAIL_TITLE = "إقرار كفالة حضورية وغرامية في حادث مروري"
BAIL_OPT = "🛡️ " + BAIL_TITLE
BAIL_BANNER = "إقرار وتعهد كفالة حضورية وغرامية في حادث مروري"
BAIL_SUB = "توثيق كفالة طرف في حادث مروري والتزام الكفيل بالحضور وسداد الحقوق المترتبة"
BAIL_LEGAL_TITLE = ""  # يبدأ مربع النص مباشرة بنص الإقرار دون عنوان فرعي
_STATE = {"sel": False, "built": False, "cleared": False}

def reset_run_state():
    _STATE["sel"] = False
    _STATE["built"] = False

BAIL_SPECS = [
    ("bail_acc_no", "رقم الحادث / المحضر", "text", "460987241", "مثال: 6004996132 أو رقم المحضر", False),
    ("bail_kind", "نوع الكفالة المعتمدة", "select", "كفالة حضورية وغرامية", [
        "كفالة حضورية وغرامية", "كفالة حضورية", "كفالة غرامية (مالية)"
    ], False),
    ("bail_acc_date_loc", "تاريخ وموقع الحادث", "text",
     "1448/06/18هـ — تقاطع طريق الملك فهد مع شارع السوق بمحافظة العارضة",
     "مثال: 1448/06/14هـ — العارضة الشارع العام", False),
    ("bail_party_status", "صفة المكفول وموجب الكفالة", "select", "الطرف الأول (خطأ 100%) — بدون تأمين ساري", [
        "الطرف الأول (خطأ 100%) — بدون تأمين ساري",
        "الطرف الأول (مشترك بالخطأ) — بدون تأمين ساري",
        "طرف بحادث إصابات — قيد استكمال التقارير الطبية",
        "قائد مركبة بدون رخصة قيادة سارية",
        "قيد استكمال التحقيق وتقدير التلفيات",
    ], False),
    ("bailed_name", "اسم المكفول (طرف الحادث - رباعياً)", "text",
     "أحمد بن سعيد بن محمد العريشي", "الاسم الرباعي للمكفول", False),
    ("bailed_id_nat", "رقم هوية / إقامة المكفول والجنسية", "text",
     "1087766554 - سعودي", "مثال: 1089911223 - سعودي", False),
    ("bailed_phone", "رقم جوال المكفول", "text", "0553344789", "05xxxxxxxx", False),
    ("bailed_vehicle", "بيانات مركبة المكفول ورقم اللوحة", "text",
     "نيسان صني فضي (س ع د 2291)", "مثال: تويوتا هايلكس (أ ب ج 1234)", False),
    ("guarantor_name", "اسم الكفيل الضامن (رباعياً)", "text",
     "عبدالله بن سعيد بن محمد العريشي", "الاسم الرباعي للكفيل الحاضر", False),
    ("guarantor_id", "رقم الهوية الوطنية للكفيل", "text", "1023344556", "10 أرقام (سجل مدني ساري)", False),
    ("guarantor_phone_rel", "رقم جوال الكفيل وصلة القرابة", "text",
     "0509988776 — شقيق", "مثال: 05xxxxxxxx — شقيق / والد", False),
    ("guarantor_work_addr", "جهة عمل الكفيل والعنوان الوطني", "text",
     "موظف بلدية محافظة العارضة — حي السوق، العارضة", "مثال: موظف حكومي — العارضة", False),
    ("bail_scope", "التزام الكفالة والحقوق المترتبة", "text",
     "إحضار المكفول لدى قسم مرور العارضة أو المحكمة المختصة متى طُلب وسداد ما يثبت شرعاً ونظاماً من حقوق خاصة أو تلفيات",
     "تفصيل الالتزام أو مبلغ التقدير إن وجد", True),
]
_TR = str.maketrans("".join(chr(0x0660 + i) for i in range(10)), "0123456789")

def _cv(d, k, fb="...................."):
    v = str((d or {}).get(k, "") or "").translate(_TR).strip()
    return v if v and v != "None" else fb

def build_bail_legal_body(vals):
    d = vals or {}
    kind = _cv(d, "bail_kind", "كفالة حضورية وغرامية")
    gn, gid = _cv(d, "guarantor_name"), _cv(d, "guarantor_id")
    gph, gwa = _cv(d, "guarantor_phone_rel"), _cv(d, "guarantor_work_addr")
    bn, bid, bveh = _cv(d, "bailed_name"), _cv(d, "bailed_id_nat"), _cv(d, "bailed_vehicle")
    ano, aloc = _cv(d, "bail_acc_no"), _cv(d, "bail_acc_date_loc")
    bst = _cv(d, "bail_party_status", "طرف في الحادث")
    scp = _cv(d, "bail_scope", "استكمال الإجراءات النظامية وسداد ما يثبت شرعاً ونظاماً")
    intro = (f"أقر أنا الكفيل الضامن المدعو / ({gn})، حامل الهوية الوطنية رقم ({gid})، وجوال وصلة قرابة ({gph})، "
             f"وعنواني ({gwa})، وأنا بكامل أهليتي المعتبرة شرعاً ونظاماً ودون إكراه أو إجبار، بأنني أكفل وأضمن "
             f"المدعو / ({bn})، حامل الهوية/الإقامة رقم ({bid})، قائد المركبة ({bveh})، طرف الحادث المروري رقم ({ano}) "
             f"وتاريخ وموقع ({aloc}) بصفته ({bst})؛ ")
    if "حضورية" in kind and "غرامية" not in kind:
        core = (f"كفالةً حضوريةً نظاميةً، ألتزم بموجبها بإحضار المكفول المذكور وتسليمه لقسم مرور محافظة العارضة "
                f"أو المحكمة المختصة فور طلبه في أي وقت لاستكمال الإجراءات ({scp})، وأتحمل كافة التبعات النظامية "
                f"المقررة بموجب نظام المرور ونظام الإجراءات الجزائية في حال الإخلال بإحضاره. ")
    elif "غرامية" in kind and "حضورية" not in kind:
        core = (f"كفالةً غراميةً ماليةً تضامنيةً، ألتزم بموجبها بالوفاء وسداد كافة التلفيات المقدرة والحقوق المالية الخاصة "
                f"المترتبة في ذمة المكفول عن الحادث المذكور ({scp}) وفق ما تقرره جهة التقدير المعتمدة أو يصدر به حكم شرعي مكتسب القطعية. ")
    else:
        core = (f"كفالةً حضوريةً وغراميةً تضامنيةً مطلقة، ألتزم بموجبها بإحضار المكفول المذكور لدى قسم مرور محافظة العارضة "
                f"أو المحكمة المختصة متى طُلب مني ذلك، كما ألتزم تضامنياً بسداد كافة ما يترتب على الحادث من حقوق خاصة "
                f"أو تلفيات مقدرة أو أرش إصابات يثبت شرعاً ونظاماً ({scp}) حال تأخر المكفول أو تعذر إحضاره أو امتناعه. ")
    return intro + core + ("وأقر بصحة بياناتي ورقم جوالي الموثق بمنصة (أبشر) للتبليغ الرسمي، ولا تبرأ ذمتي من هذه الكفالة "
                           "إلا بانتهاء المعاملة رسمياً وإشعار خطي بإخلاء الطرف من قسم مرور العارضة، والله خير الشاهدين.")

class _BailTemplateStr(str):
    def format(self, *a, **kw): return build_bail_legal_body(kw)
    def format_map(self, m): return build_bail_legal_body(m)

BAIL_RAW_TPL = _BailTemplateStr(
    "أقر أنا الكفيل الضامن المدعو / ({guarantor_name})، هوية ({guarantor_id})، جوال ({guarantor_phone_rel})، عنوان ({guarantor_work_addr})، "
    "بأنني أكفل المدعو / ({bailed_name})، هوية ({bailed_id_nat})، مركبة ({bailed_vehicle})، بالحادث ({bail_acc_no}) في ({bail_acc_date_loc}) "
    "بصفته ({bail_party_status})، ({bail_kind})، بخصوص ({bail_scope})، وألتزم بإحضاره وسداد ما يثبت شرعاً ونظاماً، والله خير الشاهدين."
)

def _validate_bail_live(vals):
    d = vals or {}
    mg = re.search(r"\d+", str(d.get("guarantor_id", "")).translate(_TR))
    mb = re.search(r"\d+", str(d.get("bailed_id_nat", "")).translate(_TR))
    gid, bid = (mg.group(0) if mg else ""), (mb.group(0) if mb else "")
    if gid and bid and gid == bid:
        st.error("⚠️ تنبيه نظامي: رقم هوية الكفيل مطابق لرقم هوية المكفول — لا يصح نظاماً كفالة الشخص لنفسه.")
    elif (gid and len(gid) != 10) or (bid and len(bid) != 10):
        st.warning("⚠️ ملاحظة تدقيق: تأكد من إدخال رقم الهوية / الإقامة الصحيح المكون من (10) أرقام.")
BAIL_SIG_JS = r"""<script id="kh-bail-sig-fix">(function(){
function initBailedPad(){
  var dock=document.querySelector('.live-sig-dock');
  if(!dock||document.getElementById('pad_bailed'))return;
  var p1=dock.querySelector('canvas[id^="pad_"]:not(#pad_officer)');
  if(!p1)return;
  dock.querySelectorAll('div,span,label,strong,b').forEach(function(el){
    if(!el.children.length&&/المقر|المستلم|المواطن|الطرف الأول/.test(el.textContent||''))el.textContent='✍️ توقيع الكفيل الضامن';
  });
  var card=p1.parentElement;
  while(card&&card.parentElement!==dock)card=card.parentElement;
  if(!card)return;
  var c2=card.cloneNode(true);
  c2.querySelectorAll('div,span,label,strong,b').forEach(function(el){
    if(!el.children.length&&(el.textContent||'').indexOf('توقيع')!==-1)el.textContent='✍️ توقيع المكفول (طرف الحادث)';
  });
  var cv=c2.querySelector('canvas');
  if(!cv)return;
  cv.id='pad_bailed';cv.removeAttribute('data-kh-touch-bound');delete cv.dataset.khTouchBound;delete cv.dataset.inkBound;delete cv.dataset.hasInk;
  var ctx=cv.getContext('2d');ctx.clearRect(0,0,cv.width,cv.height);
  c2.querySelectorAll('button').forEach(function(b){
    b.onclick=function(ev){ev.preventDefault();if(window.clearLivePad)window.clearLivePad('bailed');};
  });
  card.parentNode.insertBefore(c2,card.nextSibling);
  if(typeof LIVE_PADS!=='undefined'&&Array.isArray(LIVE_PADS)&&LIVE_PADS.indexOf('bailed')===-1)LIVE_PADS.push('bailed');
  var dr=false,lx=0,ly=0;
  function pt(e){var r=cv.getBoundingClientRect(),t=(e.touches&&e.touches[0])||e;return[(t.clientX-r.left)*(cv.width/(r.width||1)),(t.clientY-r.top)*(cv.height/(r.height||1))];}
  function st(e){dr=true;var p=pt(e);lx=p[0];ly=p[1];cv.dataset.hasInk='1';if(window.__padInk)window.__padInk['bailed']=true;}
  function mv(e){if(!dr)return;if(e.cancelable)e.preventDefault();var p=pt(e);ctx.strokeStyle='#0044cc';ctx.lineWidth=2.3;ctx.lineCap='round';ctx.beginPath();ctx.moveTo(lx,ly);ctx.lineTo(p[0],p[1]);ctx.stroke();lx=p[0];ly=p[1];}
  function en(){if(!dr)return;dr=false;if(window.syncPadToSlot)setTimeout(function(){window.syncPadToSlot('bailed');},20);}
  cv.addEventListener('mousedown',st);cv.addEventListener('mousemove',mv);window.addEventListener('mouseup',en);
  cv.addEventListener('touchstart',st,{passive:true});cv.addEventListener('touchmove',mv,{passive:false});cv.addEventListener('touchend',en,{passive:true});
}
function fixBail(root){
  var s=root.getElementById?root.getElementById('a4Sheet'):root.querySelector('#a4Sheet');
  if(!s)return;
  var b=s.querySelector('.doc-banner');
  if(!b||(b.textContent||'').indexOf('كفالة')===-1)return;
  if(root===document)initBailedPad();
  if(s.dataset.bailFixed==='1')return;
  var tbl=s.querySelector('table.sig-tbl');
  if(!tbl||!tbl.rows||tbl.rows.length<2)return;
  var hr=tbl.rows[0],br=tbl.rows[1],doc=s.ownerDocument||document;
  if(hr.cells.length===2&&br.cells.length===2){
    hr.cells[0].textContent='إقرار وتوقيع الكفيل الضامن';
    br.cells[0].querySelectorAll('div,span').forEach(function(n){if(!n.children.length&&/المقر|المستلم/.test(n.textContent||''))n.textContent='الكفيل الضامن';});
    var mth=hr.cells[0].cloneNode(true);mth.textContent='إقرار وتوقيع المكفول (طرف الحادث)';
    hr.insertBefore(mth,hr.cells[1]);
    var mtd=br.cells[0].cloneNode(false);
    var sl=doc.createElement('img');sl.id='slot_bailed';sl.className='sig-slot-img';sl.style.display='none';
    mtd.innerHTML='<div style="font-weight:800;font-size:11.5px;color:#0f3d2e;">المكفول (طرف الحادث)</div>';
    mtd.appendChild(sl);br.insertBefore(mtd,br.cells[1]);
    [hr,br].forEach(function(r){Array.from(r.cells).forEach(function(c){c.style.setProperty('width','33.33%','important');});});
    Array.from(tbl.rows).forEach(function(r){if(r!==hr&&r!==br&&r.cells.length===1&&r.cells[0].colSpan===2)r.cells[0].colSpan=3;});
  }
  s.dataset.bailFixed='1';if(root===document&&window.__khafarBindAllTouchPads)window.__khafarBindAllTouchPads();
}
try{fixBail(document);}catch(e){}
addEventListener('load',function(){try{fixBail(document);}catch(e){}});
addEventListener('beforeprint',function(){try{fixBail(document);}catch(e){}});
})();</script>"""
def _is_veh_dict(d):
    return isinstance(d, dict) and any(
        isinstance(v, str) and len(v) < 120 and (
            ("إقرار" in v and ("تسليم مركبة" in v or "استلام مركبة" in v)) or "إرفاق صور المركبة" in v
        )
        for v in d.values()
    )

def _adapt_fields(proto_fields, all_forms):
    if not proto_fields: return []
    f0 = proto_fields[0]
    if isinstance(f0, dict):
        kk = next((k for k in ("key", "id", "name", "field", "k") if k in f0), "key")
        lk = next((k for k in ("label", "title", "caption", "lbl") if k in f0), "label")
        tk = next((k for k in ("type", "kind", "widget", "input_type") if k in f0), None)
        dk = next((k for k in ("default", "value", "val", "initial") if k in f0), None)
        pk = next((k for k in ("placeholder", "hint", "help", "ph") if k in f0), None)
        ok, sel_t, wk = None, "select", None
        for fm in all_forms:
            if not isinstance(fm, dict): continue
            for fv in fm.values():
                if isinstance(fv, list):
                    for fd in fv:
                        if isinstance(fd, dict):
                            for cand in ("options", "choices", "items", "opts"):
                                if cand in fd and isinstance(fd[cand], (list, tuple)):
                                    ok = cand
                                    if tk and tk in fd: sel_t = fd[tk]
                            for wc in ("full", "full_width", "wide", "span", "colspan"):
                                if fd.get(wc) in (True, 2, 3, 4): wk = (wc, fd[wc])
        out = []
        for key, lbl, ftype, dflt, ph_opts, is_full in BAIL_SPECS:
            it = copy.deepcopy(f0)
            for k in ("options", "choices", "items", "opts", "full", "full_width", "wide", "span", "colspan", "visible_if", "hide_if"): it.pop(k, None)
            it[kk], it[lk] = key, lbl
            if ftype == "select" and ok:
                if tk: it[tk] = sel_t
                it[ok] = list(ph_opts)
                if dk: it[dk] = dflt
            else:
                if tk: it[tk] = "textarea" if is_full else "text"
                if dk: it[dk] = dflt
                if pk and isinstance(ph_opts, str): it[pk] = ph_opts
            it["sample"] = dflt if isinstance(dflt, str) else (dflt or "")
            if is_full and wk: it[wk[0]] = wk[1]
            out.append(it)
        return out
    if isinstance(f0, (tuple, list)):
        ln, tp = len(f0), type(f0)
        has_sel = any(isinstance(x,(tuple,list)) and len(x)>=4 and isinstance(x[3],(list,tuple)) for fm in all_forms if isinstance(fm,dict) for fv in fm.values() if isinstance(fv,list) for x in fv)
        out = []
        for key, lbl, ftype, dflt, ph_opts, _ in BAIL_SPECS:
            b = list(f0); b[0], b[1] = key, lbl
            if ln >= 3:
                if b[2] in ("text", "select", "selectbox", "textarea", "number", "date"):
                    b[2] = "select" if (ftype == "select" and has_sel) else "text"
                    if ln >= 4: b[3] = list(ph_opts) if b[2] == "select" else dflt
                else: b[2] = dflt if dflt else (ph_opts if isinstance(ph_opts, str) else "")
            out.append(tp(b))
        return out
    return []
def _is_veh_dict(d):
    return isinstance(d, dict) and any(
        isinstance(v, str) and len(v) < 120 and (
            ("إقرار" in v and ("تسليم مركبة" in v or "استلام مركبة" in v)) or "إرفاق صور المركبة" in v
        )
        for v in d.values()
    )

def _adapt_fields(proto_fields, all_forms):
    if not proto_fields: return []
    f0 = proto_fields[0]
    if isinstance(f0, dict):
        kk = next((k for k in ("key", "id", "name", "field", "k") if k in f0), "key")
        lk = next((k for k in ("label", "title", "caption", "lbl") if k in f0), "label")
        tk = next((k for k in ("type", "kind", "widget", "input_type") if k in f0), None)
        dk = next((k for k in ("default", "value", "val", "initial") if k in f0), None)
        pk = next((k for k in ("placeholder", "hint", "help", "ph") if k in f0), None)
        ok, sel_t, wk = None, "select", None
        for fm in all_forms:
            if not isinstance(fm, dict): continue
            for fv in fm.values():
                if isinstance(fv, list):
                    for fd in fv:
                        if isinstance(fd, dict):
                            for cand in ("options", "choices", "items", "opts"):
                                if cand in fd and isinstance(fd[cand], (list, tuple)):
                                    ok = cand
                                    if tk and tk in fd: sel_t = fd[tk]
                            for wc in ("full", "full_width", "wide", "span", "colspan"):
                                if fd.get(wc) in (True, 2, 3, 4): wk = (wc, fd[wc])
        out = []
        for key, lbl, ftype, dflt, ph_opts, is_full in BAIL_SPECS:
            it = copy.deepcopy(f0)
            for k in ("options", "choices", "items", "opts", "full", "full_width", "wide", "span", "colspan", "visible_if", "hide_if"): it.pop(k, None)
            it[kk], it[lk] = key, lbl
            if ftype == "select" and ok:
                if tk: it[tk] = sel_t
                it[ok] = list(ph_opts)
                if dk: it[dk] = dflt
            else:
                if tk: it[tk] = "textarea" if is_full else "text"
                if dk: it[dk] = dflt
                if pk and isinstance(ph_opts, str): it[pk] = ph_opts
            it["sample"] = dflt if isinstance(dflt, str) else (dflt or "")
            if is_full and wk: it[wk[0]] = wk[1]
            out.append(it)
        return out
    if isinstance(f0, (tuple, list)):
        ln, tp = len(f0), type(f0)
        has_sel = any(isinstance(x,(tuple,list)) and len(x)>=4 and isinstance(x[3],(list,tuple)) for fm in all_forms if isinstance(fm,dict) for fv in fm.values() if isinstance(fv,list) for x in fv)
        out = []
        for key, lbl, ftype, dflt, ph_opts, _ in BAIL_SPECS:
            b = list(f0); b[0], b[1] = key, lbl
            if ln >= 3:
                if b[2] in ("text", "select", "selectbox", "textarea", "number", "date"):
                    b[2] = "select" if (ftype == "select" and has_sel) else "text"
                    if ln >= 4: b[3] = list(ph_opts) if b[2] == "select" else dflt
                else: b[2] = dflt if dflt else (ph_opts if isinstance(ph_opts, str) else "")
            out.append(tp(b))
        return out
    return []
def _make_bail_form_dict(vp, all_forms):
    ck = next((k for k in ("category", "cat", "section", "group", "tab", "sec") if k in vp), None)
    sibs = [f for f in all_forms if isinstance(f, dict) and (not ck or f.get(ck) == vp.get(ck))]
    clean = [s for s in sibs if not any(isinstance(v, str) and ("إرفاق صور" in v or "تنازل" in v) for v in s.values())]
    proto = clean[0] if clean else vp
    bf = copy.deepcopy(proto)
    if ck: bf[ck] = vp[ck]
    for pk in ("with_photos", "allow_photos", "enable_photos", "vehicle_photos", "has_attachments"):
        if pk in bf and isinstance(bf[pk], bool): bf[pk] = False
    old_fk, flk = set(), None
    for k, v in proto.items():
        if isinstance(v, list) and len(v) >= 3 and isinstance(v[0], (dict, tuple, list)):
            if flk is None or k in ("fields", "inputs", "schema", "form_fields"): flk = k
    if flk:
        for fd in proto[flk]:
            if isinstance(fd, dict):
                for c in ("key", "id", "name", "field", "k"):
                    if isinstance(fd.get(c), str): old_fk.add(fd[c])
            elif isinstance(fd, (tuple, list)) and fd and isinstance(fd[0], str): old_fk.add(fd[0])
        bf[flk] = _adapt_fields(proto[flk], all_forms)
    for ik in ("id", "key", "code", "form_id", "slug"):
        if ik in bf: bf[ik] = BAIL_ID
    for tk in ("title", "name", "label"):
        if tk in bf and isinstance(bf[tk], str):
            bf[tk] = BAIL_OPT if str(vp.get(tk, "")).strip()[:1] in ("🚗", "📝", "✍️", "📄", "⚖️", "🛡️") else BAIL_TITLE
    for sk in ("subtitle", "sub", "desc", "description", "summary", "hint"):
        if sk in bf: bf[sk] = BAIL_SUB
    for ek in ("icon", "emoji"):
        if ek in bf: bf[ek] = "🛡️"
    for k, v in list(bf.items()):
        if k in ("id", "key", "code", "form_id", "slug", "title", "name", "label", ck): continue
        if isinstance(v, str):
            if v in old_fk: bf[k] = "bail_acc_no" if ("acc" in v or "no" in v) else "guarantor_name"
            elif len(v) > 90 or ("{" in v and "}" in v) or v.strip().startswith(("أقر", "أتعهد")): bf[k] = BAIL_RAW_TPL
            elif k in ("banner", "doc_banner", "doc_title", "official_title", "header_title") or (v.strip().startswith("إقرار") and len(v) < 90): bf[k] = BAIL_BANNER
            elif k in ("legal_title", "box_title", "clause_title") or ("نص " in v and len(v) < 85): bf[k] = BAIL_LEGAL_TITLE
            elif any(w in v for w in ("المقر", "المستلم", "المتعهد")) and len(v) < 55: bf[k] = "إقرار وتوقيع الكفيل الضامن"
        elif callable(v):
            from collections import defaultdict
            try:
                r = v(defaultdict(lambda: "X"))
                if isinstance(r, str): bf[k] = build_bail_legal_body
                elif isinstance(r, list): bf[k] = lambda d: [(l, _cv(d, fk)) for fk, l, *_ in BAIL_SPECS]
            except Exception: pass
    return bf

def _scan_inject(obj, ns_store, seen=None, depth=0):
    if depth > 5 or obj is None or isinstance(obj, (str, bytes, int, float, bool)): return 0
    if seen is None: seen = set()
    if id(obj) in seen: return 0
    seen.add(id(obj)); added = 0
    if isinstance(obj, list):
        vp = next((x for x in obj if _is_veh_dict(x)), None)
        if vp is not None:
            if not any(isinstance(x, dict) and (BAIL_ID in x.values() or any(isinstance(v, str) and BAIL_TITLE in v for v in x.values())) for x in obj):
                bf = _make_bail_form_dict(vp, [x for x in obj if isinstance(x, dict)])
                ck = next((k for k in ("category", "cat", "section", "group", "tab", "sec") if k in vp), None)
                ins = max(i for i, x in enumerate(obj) if isinstance(x, dict) and (not ck or x.get(ck) == vp.get(ck))) + 1
                obj.insert(ins, bf); ns_store["_KHAFAR_BAIL_PROTO"] = (vp, bf); added += 1
            return added
        for x in obj:
            if isinstance(x, (dict, list, tuple)): added += _scan_inject(x, ns_store, seen, depth + 1)
    elif isinstance(obj, dict):
        vp_it = next(((k, v) for k, v in obj.items() if not str(k).startswith("_KHAFAR") and _is_veh_dict(v)), None)
        if vp_it is not None:
            if BAIL_ID not in obj:
                vp = vp_it[1]
                bf = _make_bail_form_dict(vp, [v for v in obj.values() if isinstance(v, dict)])
                ck = next((k for k in ("category", "cat", "section", "group", "tab", "sec") if k in vp), None)
                items = list(obj.items())
                ins = max(i for i, (_, v) in enumerate(items) if isinstance(v, dict) and (not ck or v.get(ck) == vp.get(ck))) + 1
                items.insert(ins, (BAIL_ID, bf)); obj.clear(); obj.update(items)
                ns_store["_KHAFAR_BAIL_PROTO"] = (vp, bf); added += 1
            return added
        for k, v in list(obj.items()):
            if str(k).startswith("_KHAFAR") or inspect.ismodule(v) or inspect.isfunction(v) or inspect.isclass(v): continue
            if isinstance(v, tuple) and any(_is_veh_dict(x) for x in v):
                tmp = list(v); c = _scan_inject(tmp, ns_store, seen, depth + 1)
                if c: obj[k] = tuple(tmp); added += c
            elif isinstance(v, (dict, list)): added += _scan_inject(v, ns_store, seen, depth + 1)
    return added

def register_catalog(*namespaces):
    store = namespaces[-1] if namespaces and isinstance(namespaces[-1], dict) else {}
    return sum(_scan_inject(ns, store) for ns in namespaces if isinstance(ns, dict))

def wrap_catalog_fn(fn, g):
    raw = getattr(fn, "_kh_raw_cat_fn", fn)
    def _w(*a, **kw):
        r = raw(*a, **kw)
        if isinstance(r, (list, dict)): _scan_inject(r, g)
        return r
    _w._kh_raw_cat_fn = raw
    return _w
if not hasattr(DG, "_kh_bail_raw_btn"): DG._kh_bail_raw_btn = DG.button
if not hasattr(st, "_kh_bail_raw_btn"): st._kh_bail_raw_btn = st.button
def _fix_lbl(l):
    if not _STATE["cleared"]:
        _STATE["cleared"] = True
        try: st.cache_data.clear()
        except Exception: pass
    return l.replace("الإقرارات الميدانية (7)", "الإقرارات الميدانية (8)") if isinstance(l, str) else l
DG.button = lambda self, label, *a, **kw: DG._kh_bail_raw_btn(self, _fix_lbl(label), *a, **kw)
st.button = lambda label, *a, **kw: st._kh_bail_raw_btn(_fix_lbl(label), *a, **kw)

if not hasattr(DG, "_kh_bail_raw_sel"): DG._kh_bail_raw_sel = DG.selectbox
if not hasattr(st, "_kh_bail_raw_sel"): st._kh_bail_raw_sel = st.selectbox
def _prep_s(options, index, kw):
    opts = list(options) if options is not None else []
    ff = kw.get("format_func")
    disp = [str(ff(x)) if callable(ff) else str(x) for x in opts]
    is_dm = any(("تسليم مركبة" in s or "استلام مركبة" in s) for s in disp)
    if is_dm and not any("كفالة" in s and "حادث" in s for s in disp):
        if opts and isinstance(opts[0], str) and ("تسليم مركبة" in opts[0] or "استلام مركبة" in opts[0]):
            opts.append(BAIL_OPT)
        else:
            opts.append(BAIL_ID)
            if callable(ff): kw["format_func"] = lambda x, _f=ff: BAIL_OPT if x == BAIL_ID else _f(x)
        options = opts
    return options, index, kw, is_dm
def _trk_s(ret, kw, is_dm):
    if is_dm:
        ff = kw.get("format_func")
        lbl = str(ff(ret)) if (callable(ff) and ret is not None) else str(ret or "")
        _STATE["sel"] = (ret == BAIL_ID) or ("كفالة" in lbl and "حادث" in lbl)
    return ret
DG.selectbox = lambda self, label, options=(), index=0, *a, **kw: (lambda o, i, k, m: _trk_s(DG._kh_bail_raw_sel(self, label, o, i, *a, **k), k, m))(*_prep_s(options, index, kw))
st.selectbox = lambda label, options=(), index=0, *a, **kw: (lambda o, i, k, m: _trk_s(st._kh_bail_raw_sel(label, o, i, *a, **k), k, m))(*_prep_s(options, index, kw))

def bind_functions(g):
    register_catalog(g)
    bh = g.get("build_official_a4_html")
    if callable(bh) and not getattr(bh, '_kh_bail_wrapped', False):
        raw_bh = getattr(bh, "_kh_bail_raw_bh", bh)
        def _bh_wrap(*a, **kw):
            _STATE["built"] = True
            av = list(a) + list(kw.values())
            is_b = _STATE["sel"] or any(isinstance(x, str) and "كفالة" in x for x in av) or any(isinstance(x, dict) and BAIL_ID in x.values() for x in av)
            if is_b:
                vd = next((x for x in av if isinstance(x, dict) and ("guarantor_id" in x or "bailed_id_nat" in x)), None) or st.session_state
                _validate_bail_live({
                    "guarantor_id": next((v for k, v in vd.items() if "guarantor_id" in str(k)), ""),
                    "bailed_id_nat": next((v for k, v in vd.items() if "bailed_id_nat" in str(k)), ""),
                })
            if not is_b and kw: st.session_state['_kh_proto_bh_kw'] = {k: v for k, v in kw.items() if k not in ('fields_map', 'values', 'data', 'vals')}
            html = raw_bh(*a, **kw)
            if is_b and isinstance(html, str) and "kh-bail-sig-fix" not in html:
                html = html.replace("</body>", BAIL_SIG_JS + "\n</body>", 1) if "</body>" in html else (html + BAIL_SIG_JS)
            return html
        _bh_wrap._kh_bail_raw_bh = raw_bh; _bh_wrap._kh_bail_wrapped = True; _bh_wrap._kh_med_age_wrapped = getattr(bh, '_kh_med_age_wrapped', False)
        g["build_official_a4_html"] = _bh_wrap

def ensure_bail_rendered(g):
    if not _STATE["sel"] or _STATE["built"]: return
    _STATE["built"] = True
    st.markdown(f"### {BAIL_OPT}"); st.caption(BAIL_SUB)
    vals, c1, c2 = {}, *st.columns(2)
    for idx, (k, lbl, ft, df, po, full) in enumerate(BAIL_SPECS):
        tg = st if full else (c1 if idx % 2 == 0 else c2)
        vals[k] = tg.selectbox(lbl, po, key=f"_bi_{k}") if ft == "select" else tg.text_input(lbl, value=df, placeholder=po, key=f"_bi_{k}")
    _validate_bail_live(vals)
    bh = g.get("build_official_a4_html")
    if callable(bh):
        bkw, rows, body = dict(st.session_state.get('_kh_proto_bh_kw') or {}), [(l, _cv(vals, k)) for k, l, *_ in BAIL_SPECS], build_bail_legal_body(vals)
        for pn, prm in inspect.signature(getattr(bh, "_kh_bail_raw_bh", bh)).parameters.items():
            pl = pn.lower()
            if pl in ("form_id", "doc_id", "code", "key"): bkw[pn] = BAIL_ID
            elif pl in ("title", "doc_title", "banner", "banner_title", "header_title"): bkw[pn] = BAIL_BANNER
            elif pl in ("subtitle", "sub_title"): bkw[pn] = BAIL_SUB
            elif "legal" in pl and "title" in pl: bkw[pn] = BAIL_LEGAL_TITLE
            elif any(w in pl for w in ("legal", "body", "clause", "statement", "text")) and "title" not in pl: bkw[pn] = body
            elif "row" in pl: bkw[pn] = rows
            elif pl in ("fields_map", "values", "data", "vals"): bkw[pn] = vals
            elif prm.default is inspect._empty: bkw[pn] = ""
        comp.html(bh(**bkw), height=1850, scrolling=True)
