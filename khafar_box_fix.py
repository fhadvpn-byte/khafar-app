import re, streamlit as st
import streamlit.components.v1 as comp
from streamlit.delta_generator import DeltaGenerator as DG
CAUSES = [
"انحراف مفاجئ","دوران غير نظامي","تجاوز غير نظامي",
"عدم التقيد بالإشارة","السرعة الزائدة","السائق تحت تأثير المخدر",
"عدم ترك مسافة آمنة","الانشغال بغير الطريق (الجوال)",
"عدم الانتباه واليقظة","الرجوع للخلف بشكل خاطئ",
"دخول طريق رئيسي دون تأكد","عدم إعطاء الأولوية بتقاطع",
]
CAUSES += [
"عدم إعطاء الأولوية بالدوار","عدم التقيد بعلامة قف",
"تغيير المسار فجأة","السير عكس الاتجاه",
"الوقوف المفاجئ بالطريق","الوقوف الخاطئ بالطريق",
"تجاوز خاطئ في منعطف","فقدان السيطرة بمنعطف جبلي",
"الإرهاق أو النعاس","التفحيط أو القيادة بتهور",
"انفجار أو تلف الإطار","خلل فني بالمكابح أو المقود",
"عبور المشاة من غير ممرهم","عدم إعطاء الأولوية للمشاة",
]
CAUSES += [
"اعتراض حيوانات سائبة","فتح باب المركبة فجأة",
"تحرك مركبة بدون تأمين","القيادة بدون أنوار ليلاً",
"سقوط حمولة غير مؤمنة","انزلاق بسبب الأمطار والسيول",
"وجود حفريات أو عوائق","قيادة غير مؤهل للقيادة",
"الهروب من موقع الحادث",
]
def _mrg(o,e):
 b=[str(x)for x in o if str(x)not in("أخرى","اخرى")]
 return b+[x for x in e if x not in b and x!="أخرى"]+["أخرى"]
if not hasattr(DG,"_ks"):
 DG._ks=DG.selectbox
 def _sl(self,label,options=(),index=0,*a,**k):
  o=list(options or[])
  if "انحراف مفاجئ" in o:
   options=_mrg(o,CAUSES)
   if isinstance(index,int)and 0<=index<len(o)and str(o[index])in options:index=options.index(str(o[index]))
  return DG._ks(self,label,options,index,*a,**k)
 DG.selectbox=_sl
 if hasattr(st,"_main"):st.selectbox=st._main.selectbox
TAG = """<style id="kh-box-fix">
canvas{touch-action:none!important;-ms-touch-action:none!important;-webkit-user-select:none!important;user-select:none!important}
table:not(.sig-dock-tbl):not(.sig-tbl){width:100%!important;max-width:100%!important;table-layout:fixed!important;border-collapse:collapse!important}
table:not(.sig-tbl) th,table:not(.sig-tbl) td{box-sizing:border-box!important;overflow:hidden!important;white-space:normal!important;word-break:normal!important;overflow-wrap:break-word!important;padding-left:2px!important;padding-right:2px!important}
table.sig-tbl,table.sig-tbl th,table.sig-tbl td,.sig-cell,.sig-footer{overflow:visible!important;height:auto!important;max-height:none!important;white-space:normal!important}
table.sig-tbl img.sig-slot-img,table.sig-tbl img[id^="slot_"]{height:38px!important;max-height:40px!important;max-width:92%!important;object-fit:contain!important;display:block!important;margin:2px auto!important;visibility:visible!important;opacity:1!important}
</style><script id="kh-box-js">(function(){function fit(d){
d.querySelectorAll('table').forEach(function(t){
if(t.closest('.live-sig-dock')||t.matches('.data-tbl,.sig-tbl')||!t.rows.length||(t.tHead&&t.tHead.rows.length>1))return;
var c=t.rows[0].cells,s=0,w=[],i,x,v;if(!c||c.length<5)return;
for(i=0;i<c.length;i++){if(c[i].colSpan>1||c[i].rowSpan>1)return;x=c[i].textContent||'';v=/^(\u0645|#)$/.test(x.trim())?4.5:/\u062c\u0646\u0633 \u0627\u0644\u0633\u0627\u0626\u0642|\u0631\u0642\u0645 \u0627\u0644\u0637\u0631\u064a\u0642|\u0627\u0644\u0648\u0642\u062a/.test(x)?7:/\u062c\u0633\u0627\u0645\u0629|\u062c\u0646\u0633\u064a\u0629|\u0627\u0644\u062a\u063a\u0637\u064a\u0629/.test(x)?9:/\u0631\u0642\u0645 \u0627\u0644\u062d\u0627\u062f\u062b|\u0631\u0642\u0645 \u0627\u0644\u0645\u062e\u0627\u0644\u0641\u0629|\u0647\u0648\u064a\u0629|\u0627\u0644\u0644\u0648\u062d\u0629/.test(x)?15:/\u0633\u0628\u0628|\u0627\u0644\u0645\u062e\u0627\u0644\u0641\u0629|\u0645\u0644\u0627\u062d\u0638\u0627\u062a/.test(x)?18.5:12;w.push(v);s+=v;}
if(s<=0)return;Array.from(t.rows).forEach(function(r){if(r.cells.length===w.length)for(i=0;i<w.length;i++)r.cells[i].style.width=(w[i]*100/s).toFixed(1)+'%';});});
d.querySelectorAll('th,td').forEach(function(c){
if(c.closest('.live-sig-dock,.sig-tbl')||c.querySelector('table,img,svg,canvas,input,select,button'))return;
var t=(c.textContent||'').trim();if(!t)return;
if(/^[0-9\u0660-\u0669A-Za-z\\-\\/.#+:]{6,}$/.test(t))c.style.cssText+=';direction:ltr;unicode-bidi:embed;white-space:'+(t.length>13?'normal':'nowrap')+';overflow-wrap:anywhere;text-align:center;font-size:'+(t.length>12?'8.5px':'9.5px')+'!important;';
var cw=c.clientWidth||0,f=11;while(cw>16&&c.scrollWidth>cw&&f>7.5){f-=0.5;c.style.setProperty('font-size',f+'px','important');}});
}try{fit(document);}catch(e){}setTimeout(function(){try{fit(document);}catch(e){}},200);addEventListener('beforeprint',function(){try{fit(document);}catch(e){}});})();</script>"""
def inject_box(h):
 if not isinstance(h,str)or"kh-box-fix"in h or("<table"not in h and"</html>"not in h):return h
 # حقن قبل آخر </body> فقط — تجنّب مطابقة </body> داخل سلاسل JS (buildCleanPrintHtml)
 matches=list(re.finditer(r"</body>",h,flags=re.I))
 if not matches:return h+TAG
 m=matches[-1]
 return h[:m.start()]+TAG+h[m.start():]
if not hasattr(comp,"_kh_oh"):
 comp._kh_oh=comp.html
 comp.html=lambda h,*a,**k:comp._kh_oh(inject_box(h),*a,**k)
def patch_takmeel(g):
 _ch=comp.html
 if not getattr(_ch,"_kh_b",False):
  comp.html=lambda h,*a,**k:_ch(inject_box(h),*a,**k);comp.html._kh_b=True
 for v in list(g.values()):
  if isinstance(v,list)and"انحراف مفاجئ"in v:v[:]=_mrg(v,CAUSES)
 for k,fn in list(g.items()):
  if callable(fn)and getattr(fn,"__module__","")==g.get("__name__")and any(w in k.lower()for w in("html","print","sheet","report","preview","table","a4")):
   g[k]=(lambda f:lambda *a,**kw:inject_box(f(*a,**kw)))(fn)
 af,la=g.get("_auto_fill_from_day"),g.get("list_accidents")
 if callable(af)and callable(la)and not getattr(af,"_kw",False):
  std=set(CAUSES[:6])|{"أخرى"}|{c for c in af.__code__.co_consts if isinstance(c,str)}
  def _w(*a,**kw):
   rla=g["list_accidents"]
   g["list_accidents"]=lambda *x,**y:[{**r,**{k:"أخرى"for k in("cause","reason","سبب_الحادث","سبب الحادث")if isinstance(r.get(k),str)and r[k]not in std}}if isinstance(r,dict)else r for r in(rla(*x,**y)or[])]
   try:return af(*a,**kw)
   finally:g["list_accidents"]=rla
  _w._kw=True;g["_auto_fill_from_day"]=_w
