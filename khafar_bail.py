import copy, re
import streamlit as st

BAIL_ID = "decl_accident_bail"
BAIL_TITLE = "إقرار كفالة حضورية وغرامية في حادث مروري"
BAIL_BANNER = "إقرار وتعهد كفالة حضورية وغرامية في حادث مروري"
BAIL_SUB = "توثيق كفالة طرف في حادث مروري والتزام الكفيل بالحضور وسداد الحقوق المترتبة"
BAIL_LEGAL_TITLE = "نص إقرار الكفالة والتعهد النظامي المعتمد:"

BAIL_SPECS = [
    ("bail_acc_no", "رقم الحادث / المحضر", "text", "", "مثال: 460988410 أو رقم نجم/أوتار", False),
    ("bail_kind", "نوع الكفالة المعتمدة", "select", "كفالة حضورية وغرامية", [
        "كفالة حضورية وغرامية", "كفالة حضورية", "كفالة غرامية (مالية)"
    ], False),
    ("bail_acc_date_loc", "تاريخ وموقع الحادث", "text", "", "مثال: 1448/06/14هـ — العارضة الشارع العام", False),
    ("bail_party_status", "صفة المكفول وحالة التأمين", "select", "الطرف الأول (خطأ 100%) — بدون تأمين ساري", [
        "الطرف الأول (خطأ 100%) — بدون تأمين ساري",
        "الطرف الأول (خطأ 75%) — بدون تأمين ساري",
        "الطرف الأول (خطأ 50%) — بدون تأمين ساري",
        "طرف في حادث به إصابات — قيد استكمال التقرير الطبي",
        "طرف في حادث — تأمين ساري وبانتظار استكمال الإجراءات",
        "قائد مركبة بدون رخصة قيادة سارية",
        "قيد استكمال التحقيق وتقدير التلفيات",
    ], False),
    ("bailed_name", "اسم المكفول (طرف الحادث - رباعياً)", "text", "", "الاسم الرباعي للمكفول", False),
    ("bailed_id_nat", "رقم هوية / إقامة المكفول والجنسية", "text", "", "مثال: 1089911223 - سعودي", False),
    ("bailed_phone", "رقم جوال المكفول", "text", "", "05xxxxxxxx", False),
    ("bailed_vehicle", "بيانات مركبة المكفول ورقم اللوحة", "text", "", "مثال: تويوتا هايلكس (أ ب ج 1234)", False),
    ("guarantor_name", "اسم الكفيل الضامن (رباعياً)", "text", "", "الاسم الرباعي للكفيل الحاضر", False),
    ("guarantor_id", "رقم الهوية الوطنية للكفيل", "text", "", "10 أرقام (سجل مدني ساري)", False),
    ("guarantor_phone_rel", "رقم جوال الكفيل وصلة القرابة", "text", "", "مثال: 05xxxxxxxx — شقيق / والد / قريب", False),
    ("guarantor_work_addr", "جهة عمل الكفيل والعنوان الوطني", "text", "", "مثال: موظف حكومي — العارضة حي الروابي", False),
    ("bail_scope", "موجب الكفالة والالتزام المترتب", "text",
     "إحضار المكفول لدى قسم مرور العارضة أو المحكمة المختصة متى طُلب وسداد ما يثبت شرعاً ونظاماً من حقوق خاصة أو تلفيات",
     "تفصيل موجب الكفالة أو التقدير المالي إن وجد", True),
]

_TR = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")

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
    "أقر أنا الكفيل الضامن المدعو / ({guarantor_name})، حامل الهوية الوطنية رقم ({guarantor_id})، وجوال ({guarantor_phone_rel})، "
    "وعنواني ({guarantor_work_addr})، وأنا بكامل أهليتي المعتبرة شرعاً ونظاماً، بأنني أكفل وأضمن المدعو / ({bailed_name})، "
    "حامل الهوية رقم ({bailed_id_nat})، قائد المركبة ({bailed_vehicle})، في الحادث المروري رقم ({bail_acc_no}) وتاريخ وموقع "
    "({bail_acc_date_loc}) بصفته ({bail_party_status})، ({bail_kind})، وذلك بخصوص ({bail_scope})، ألتزم بموجبها بإحضار المكفول "
    "لدى قسم مرور محافظة العارضة أو المحكمة المختصة متى طُلب وسداد ما يثبت شرعاً ونظاماً، وأقر بصحة بياناتي للتبليغ عبر أبشر، "
    "ولا تبرأ ذمتي إلا بإخلاء طرف خطي من قسم مرور العارضة، والله خير الشاهدين."
)

BAIL_SIG_JS = r"""<script id="kh-bail-sig-fix">(function(){
function fixBail(root){
  var s=root.getElementById?root.getElementById('a4Sheet'):root.querySelector('#a4Sheet');
  if(!s||s.dataset.bailFixed==='1')return;
  var b=s.querySelector('.doc-banner');
  if(!b||(b.textContent||'').indexOf('كفالة')===-1)return;
  var tbl=s.querySelector('table.sig-tbl');
  if(!tbl||!tbl.rows||tbl.rows.length<2)return;
  var hr=tbl.rows[0],br=tbl.rows[1],doc=s.ownerDocument||document;
  if(hr.cells.length===2&&br.cells.length===2){
    hr.cells[0].textContent='إقرار وتوقيع الكفيل الضامن';
    var mth=hr.cells[0].cloneNode(true);mth.textContent='إقرار وتوقيع المكفول (طرف الحادث)';
    hr.insertBefore(mth,hr.cells[1]);
    var mtd=br.cells[0].cloneNode(false);
    var sl=s.querySelector('img#slot_bailed,img#slot_party2,img#slot_p2');
    if(!sl){sl=doc.createElement('img');sl.id='slot_bailed';sl.className='sig-slot-img';sl.style.display='none';}
    mtd.innerHTML='<div style="font-weight:800;font-size:11.5px;color:#0f3d2e;">المكفول (طرف الحادث)</div>';
    mtd.appendChild(sl);br.insertBefore(mtd,br.cells[1]);
    [hr,br].forEach(function(r){Array.from(r.cells).forEach(function(c){c.style.setProperty('width','33.33%','important');});});
  }else if(hr.cells.length>=3){
    if((hr.cells[0].textContent||'').indexOf('وحدة الحوادث')===-1)hr.cells[0].textContent='إقرار وتوقيع الكفيل الضامن';
    if((hr.cells[1].textContent||'').indexOf('وحدة الحوادث')===-1)hr.cells[1].textContent='إقرار وتوقيع المكفول (طرف الحادث)';
  }
  s.dataset.bailFixed='1';
}
try{fixBail(document);}catch(e){}
addEventListener('load',function(){try{fixBail(document);}catch(e){}});
addEventListener('beforeprint',function(){try{fixBail(document);}catch(e){}});
})();</script>"""

def _validate_bail_live(vals):
    d = vals or {}
    m_g = re.search(r"\d+", str(d.get("guarantor_id", "")).translate(_TR))
    m_b = re.search(r"\d+", str(d.get("bailed_id_nat", "")).translate(_TR))
    gid = m_g.group(0) if m_g else ""
    bid = m_b.group(0) if m_b else ""
    if gid and bid and gid == bid:
        st.error("⚠️ تنبيه نظامي: رقم هوية الكفيل مطابق لرقم هوية المكفول — لا يصح نظاماً كفالة الشخص لنفسه.")
    elif (gid and len(gid) != 10) or (bid and len(bid) != 10):
        st.warning("⚠️ ملاحظة تدقيق: تأكد من إدخال رقم الهوية / الإقامة الصحيح المكون من (10) أرقام.")

def _adapt_fields(proto_fields, all_forms):
    if not proto_fields: return []
    f0 = proto_fields[0]
    if isinstance(f0, dict):
        kk = next((k for k in ("key", "id", "name", "field") if k in f0), "key")
        lk = next((k for k in ("label", "title", "caption") if k in f0), "label")
        tk = next((k for k in ("type", "kind", "widget") if k in f0), None)
        dk = next((k for k in ("default", "value", "val") if k in f0), None)
        pk = next((k for k in ("placeholder", "hint", "help") if k in f0), None)
        ok, sel_t, wk = None, "select", None
        for fm in all_forms:
            for fd in (fm.get("fields") or []) if isinstance(fm, dict) else []:
                if isinstance(fd, dict):
                    for cand in ("options", "choices", "items"):
                        if cand in fd and isinstance(fd[cand], (list, tuple)):
                            ok = cand
                            if tk and tk in fd: sel_t = fd[tk]
                    for wc in ("full", "full_width", "wide", "span", "colspan"):
                        if fd.get(wc) in (True, 2, 3, 4): wk = (wc, fd[wc])
        out = []
        for key, lbl, ftype, dflt, ph_or_opts, is_full in BAIL_SPECS:
            item = copy.deepcopy(f0)
            for k in ("options", "choices", "items", "full", "full_width", "wide", "span", "colspan"): item.pop(k, None)
            item[kk], item[lk] = key, lbl
            if ftype == "select" and ok:
                if tk: item[tk] = sel_t
                item[ok] = list(ph_or_opts)
                if dk: item[dk] = dflt
            else:
                if dk: item[dk] = dflt
                if pk and isinstance(ph_or_opts, str): item[pk] = ph_or_opts
            if is_full and wk: item[wk[0]] = wk[1]
            out.append(item)
        return out
    if isinstance(f0, (tuple, list)):
        ln, tp = len(f0), type(f0)
        out = []
        for key, lbl, ftype, dflt, ph_or_opts, is_full in BAIL_SPECS:
            base = list(f0)
            base[0], base[1] = key, lbl
            if ln >= 3:
                if base[2] in ("text", "select", "selectbox", "textarea", "number", "date"):
                    base[2] = "select" if (ftype == "select" and any(len(x)>=4 and isinstance(x[3],(list,tuple)) for fm in all_forms if isinstance(fm,dict) for x in (fm.get("fields") or []) if isinstance(x,(list,tuple)))) else "text"
                    if ln >= 4: base[3] = list(ph_or_opts) if base[2] == "select" else dflt
                else:
                    base[2] = dflt if dflt else (ph_or_opts if isinstance(ph_or_opts, str) else "")
            out.append(tp(base))
        return out
    return []

def _make_bail_form_dict(veh_proto, all_forms):
    cat_k = next((k for k in ("category", "cat", "section", "group", "tab") if k in veh_proto), None)
    siblings = [f for f in all_forms if isinstance(f, dict) and (not cat_k or f.get(cat_k) == veh_proto.get(cat_k))]
    two_p = next((s for s in siblings if any(isinstance(s.get(pk), list) and len(s[pk]) >= 3 for pk in ("live_pads", "pads", "sig_pads", "signatures", "parties"))), veh_proto)
    bf = copy.deepcopy(two_p)
    if cat_k: bf[cat_k] = veh_proto[cat_k]
    for ik in ("id", "key", "code", "form_id", "slug"):
        if ik in bf: bf[ik] = BAIL_ID
    for tk in ("title", "name", "label"):
        if tk in bf:
            bf[tk] = ("🛡️ " + BAIL_TITLE) if str(veh_proto.get(tk, "")).strip()[:1] in ("🚗", "📝", "✍️", "📄", "⚖️", "🛡️") else BAIL_TITLE
    for sk in ("subtitle", "desc", "description", "summary", "hint"):
        if sk in bf: bf[sk] = BAIL_SUB
    for ek in ("icon", "emoji"):
        if ek in bf: bf[ek] = "🛡️"
    for bk in ("banner", "doc_title", "official_title", "header_title"):
        if bk in bf: bf[bk] = BAIL_BANNER
    for ltk in ("legal_title", "box_title", "clause_title"):
        if ltk in bf: bf[ltk] = BAIL_LEGAL_TITLE
    for tpl_k in ("template", "legal_template", "body_template", "legal_text", "body", "text", "content"):
        if tpl_k in bf and isinstance(bf[tpl_k], str): bf[tpl_k] = BAIL_RAW_TPL
    if "fields" in bf and isinstance(bf["fields"], list):
        bf["fields"] = _adapt_fields(veh_proto.get("fields") or bf["fields"], all_forms)
    for pk in ("live_pads", "pads", "sig_pads"):
        if pk in bf and isinstance(bf[pk], list) and bf[pk]:
            p0 = bf[pk][0]
            if isinstance(p0, dict):
                ik = next((k for k in ("id", "key", "pad_id") if k in p0), "id")
                lk = next((k for k in ("label", "title", "name") if k in p0), "label")
                bf[pk] = [{**copy.deepcopy(p0), ik: "guarantor", lk: "توقيع الكفيل الضامن"},
                          {**copy.deepcopy(p0), ik: "bailed", lk: "توقيع المكفول (طرف الحادث)"},
                          {**copy.deepcopy(p0), ik: "officer", lk: "مستلم الخفر المناوب"}]
            elif isinstance(p0, (tuple, list)) and len(p0) >= 2:
                tp = type(p0)
                bf[pk] = [tp(["guarantor", "توقيع الكفيل الضامن"] + list(p0[2:])),
                          tp(["bailed", "توقيع المكفول (طرف الحادث)"] + list(p0[2:])),
                          tp(["officer", "مستلم الخفر المناوب"] + list(p0[2:]))]
    return bf

def register_catalog(*namespaces):
    for ns in namespaces:
        if not isinstance(ns, dict): continue
        for gval in list(ns.values()):
            if isinstance(gval, list) and gval and all(isinstance(x, dict) for x in gval):
                vp = next((x for x in gval if any("استلام مركبة" in str(v) for v in x.values() if isinstance(v, str))), None)
                if vp and not any(BAIL_ID in x.values() for x in gval):
                    bf = _make_bail_form_dict(vp, gval)
                    cat_k = next((k for k in ("category", "cat", "section", "group", "tab") if k in vp), None)
                    ins = max(i for i, x in enumerate(gval) if not cat_k or x.get(cat_k) == vp.get(cat_k)) + 1
                    gval.insert(ins, bf)
                    ns["_KHAFAR_BAIL_PROTO"] = (vp, bf)
            elif isinstance(gval, dict) and gval and all(isinstance(v, dict) for v in gval.values()):
                vp_item = next(((k, v) for k, v in gval.items() if any("استلام مركبة" in str(sv) for sv in v.values() if isinstance(sv, str))), None)
                if vp_item and BAIL_ID not in gval:
                    bf = _make_bail_form_dict(vp_item[1], list(gval.values()))
                    gval[BAIL_ID] = bf
                    ns["_KHAFAR_BAIL_PROTO"] = (vp_item[1], bf)

def _has_const(code_obj, target):
    for c in getattr(code_obj, "co_consts", ()):
        if c == target: return True
        if hasattr(c, "co_consts") and _has_const(c, target): return True
    return False

def bind_functions(g):
    register_catalog(g)
    pair = g.get("_KHAFAR_BAIL_PROTO")
    vp = pair[0] if pair else {}
    pid = next((vp.get(k) for k in ("id", "key", "code", "form_id", "slug") if vp.get(k)), None)

    if pid:
        for fn_name, fn in list(g.items()):
            if fn_name.startswith("_khafar") or fn_name == "build_official_a4_html" or not callable(fn) or getattr(fn, "_kh_bail_w", False):
                continue
            co = getattr(fn, "__code__", None)
            if not co or any(w in getattr(co, "co_names", ()) for w in ("text_input", "selectbox", "columns", "button")):
                continue
            if _has_const(co, pid):
                def _mk_wrap(_orig, _pid=pid):
                    def _w(*a, **kw):
                        used = any(x == BAIL_ID or (isinstance(x, dict) and BAIL_ID in x.values()) for x in list(a) + list(kw.values()))
                        if not used: return _orig(*a, **kw)
                        vals = next((x for x in list(a) + list(kw.values()) if isinstance(x, dict) and ("guarantor_name" in x or "bailed_name" in x or "bail_kind" in x)), {})
                        pa = [_pid if x == BAIL_ID else x for x in a]
                        pkw = {k: (_pid if v == BAIL_ID else v) for k, v in kw.items()}
                        try: pr = _orig(*pa, **pkw)
                        except Exception: return build_bail_legal_body(vals)
                        if isinstance(pr, str):
                            return BAIL_LEGAL_TITLE if len(pr) < 85 and "نص" in pr else (BAIL_BANNER if len(pr) < 85 else build_bail_legal_body(vals))
                        if isinstance(pr, list) and pr and isinstance(pr[0], tuple) and len(pr[0]) == 2:
                            return [(lbl, _cv(vals, k)) for k, lbl, *_ in BAIL_SPECS]
                        return pr
                    _w._kh_bail_w = True
                    return _w
                g[fn_name] = _mk_wrap(fn)

    bh = g.get("build_official_a4_html")
    if callable(bh) and not getattr(bh, "_kh_bail_html", False):
        def _bh_wrap(*a, **kw):
            all_v = list(a) + list(kw.values())
            is_b = any(isinstance(x, str) and "كفالة" in x for x in all_v) or any(isinstance(x, dict) and BAIL_ID in x.values() for x in all_v)
            if is_b:
                vdict = next((x for x in all_v if isinstance(x, dict) and ("guarantor_id" in x or "bailed_id_nat" in x)), None)
                if vdict is None:
                    vdict = {k: v for k, v in st.session_state.items() if isinstance(k, str)}
                _validate_bail_live({
                    "guarantor_id": next((v for k, v in vdict.items() if "guarantor_id" in str(k)), ""),
                    "bailed_id_nat": next((v for k, v in vdict.items() if "bailed_id_nat" in str(k)), ""),
                })
            html = bh(*a, **kw)
            if is_b and isinstance(html, str) and "kh-bail-sig-fix" not in html:
                html = html.replace("</body>", BAIL_SIG_JS + "\n</body>", 1) if "</body>" in html else (html + BAIL_SIG_JS)
            return html
        _bh_wrap._kh_bail_html = True
        g["build_official_a4_html"] = _bh_wrap
