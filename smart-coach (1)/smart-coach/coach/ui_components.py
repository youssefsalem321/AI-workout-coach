"""Small client-side widgets for Streamlit (HTML/JS, no server round-trips)."""
from __future__ import annotations


def rest_timer_html(label: str = "Rest timer", presets: tuple[int, ...] = (60, 90, 120, 180)) -> str:
    buttons = "".join(f'<button onclick="startT({p})">{p}s</button>' for p in presets)
    return f"""
<div style="font-family:system-ui,sans-serif;display:flex;align-items:center;gap:10px;flex-wrap:wrap">
  <b>{label}</b>
  <span id="t" style="font-size:28px;min-width:72px;font-variant-numeric:tabular-nums">0:00</span>
  {buttons}
  <button onclick="stopT()">Stop</button>
</div>
<style>button{{padding:8px 12px;border-radius:8px;border:1px solid #8884;background:#8881;cursor:pointer;font-size:15px}}</style>
<script>
let timer=null,left=0;
function fmt(s){{return Math.floor(s/60)+":"+String(s%60).padStart(2,"0")}}
function beep(){{try{{const c=new (window.AudioContext||window.webkitAudioContext)(),o=c.createOscillator();
  o.frequency.value=880;o.connect(c.destination);o.start();setTimeout(()=>o.stop(),400);}}catch(e){{}}
  if(navigator.vibrate)navigator.vibrate([200,100,200]);}}
function stopT(){{clearInterval(timer);timer=null;left=0;document.getElementById("t").textContent="0:00";}}
function startT(s){{clearInterval(timer);left=s;document.getElementById("t").textContent=fmt(left);
  timer=setInterval(()=>{{left--;document.getElementById("t").textContent=fmt(Math.max(left,0));
    if(left<=0){{clearInterval(timer);beep();}}}},1000);}}
</script>
"""
