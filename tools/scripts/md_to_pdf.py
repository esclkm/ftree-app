#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Универсальный сборщик: один .md -> самодостаточный .html (фото base64 + Mermaid).
PDF печатается отдельно через headless Chrome.

Запуск: python3 tools/scripts/md_to_pdf.py <input.md> <output.html> [Заголовок]
"""
import os, re, base64, html as H, sys
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from md_clean import strip_wikilinks  # ссылки Obsidian → простой текст


def build(md_path, html_path, title="Родословная"):
    BASE=os.path.dirname(os.path.abspath(md_path))
    combined=strip_wikilinks(open(md_path,encoding="utf-8").read())
    def img_data(rel):
        path=os.path.normpath(os.path.join(BASE,rel))
        if not os.path.exists(path): return None
        ext=os.path.splitext(path)[1].lstrip(".").lower()
        mime={"jpg":"jpeg","jpeg":"jpeg","png":"png","webp":"webp"}.get(ext,"jpeg")
        return f"data:image/{mime};base64,"+base64.b64encode(open(path,'rb').read()).decode()
    def inline(s):
        s=H.escape(s)
        s=re.sub(r"\*\*(.+?)\*\*",r"<strong>\1</strong>",s)
        s=re.sub(r"(?<!\*)\*(?!\*)(.+?)\*",r"<em>\1</em>",s)
        s=re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)",r'<a href="\2">\1</a>',s)
        s=re.sub(r"(?<!\")(https?://[^\s<]+)",r'<a href="\1">\1</a>',s)
        return s
    lines=combined.split("\n"); out=[]; i=0; in_list=False
    def close_list():
        nonlocal in_list
        if in_list: out.append("</ul>"); in_list=False
    while i<len(lines):
        ln=lines[i]
        if ln.strip().startswith("```mermaid"):
            close_list(); j=i+1; buf=[]
            while j<len(lines) and not lines[j].strip().startswith("```"): buf.append(lines[j]); j+=1
            out.append('<pre class="mermaid">'+H.escape("\n".join(buf))+'</pre>'); i=j+1; continue
        if ln.strip().startswith("```"):
            j=i+1; buf=[]
            while j<len(lines) and not lines[j].strip().startswith("```"): buf.append(lines[j]); j+=1
            out.append("<pre>"+H.escape("\n".join(buf))+"</pre>"); i=j+1; continue
        if "<img" in ln:
            close_list()
            def repl(m):
                src=m.group(1); d=img_data(src) if src.startswith("../") else None
                cap=m.group(2) or ""
                return f'<figure><img src="{d or src}">{("<figcaption>"+inline(cap.strip("* "))+"</figcaption>") if cap.strip() else ""}</figure>'
            out.append('<div class="photos">'+re.sub(r'<img src="([^"]+)"[^>]*>\s*(\*[^*]*\*)?',repl,ln)+'</div>'); i+=1; continue
        if ln.strip().startswith("|") and i+1<len(lines) and re.match(r"^\s*\|[-: |]+\|\s*$",lines[i+1]):
            close_list(); hdr=[c.strip() for c in ln.strip().strip("|").split("|")]
            out.append("<table><thead><tr>"+"".join(f"<th>{inline(c)}</th>" for c in hdr)+"</tr></thead><tbody>")
            j=i+2
            while j<len(lines) and lines[j].strip().startswith("|"):
                cells=[c.strip() for c in lines[j].strip().strip("|").split("|")]
                out.append("<tr>"+"".join(f"<td>{inline(c)}</td>" for c in cells)+"</tr>"); j+=1
            out.append("</tbody></table>"); i=j; continue
        m=re.match(r"^(#{1,6})\s+(.*)",ln)
        if m:
            close_list(); lvl=len(m.group(1))
            out.append(f'<h{lvl}{" class=\"card\"" if lvl==4 else ""}>{inline(m.group(2))}</h{lvl}>'); i+=1; continue
        if ln.startswith(">"):
            close_list(); out.append("<blockquote>"+inline(ln.lstrip('> ').rstrip())+"</blockquote>"); i+=1; continue
        if re.match(r"^\s*[-*]\s+",ln):
            if not in_list: out.append("<ul>"); in_list=True
            cls=' class="warn"' if "Несоответ" in ln or "Niezgod" in ln or "Discrepan" in ln else ""
            out.append(f"<li{cls}>"+inline(re.sub(r"^\s*[-*]\s+","",ln))+"</li>"); i+=1; continue
        if ln.strip()=="---": close_list(); out.append('<hr class="part">'); i+=1; continue
        if ln.strip()=="": close_list(); i+=1; continue
        close_list(); out.append("<p>"+inline(ln)+"</p>"); i+=1
    close_list()
    HTML=f"""<!doctype html><html><head><meta charset="utf-8"><title>{H.escape(title)}</title>
<style>
 body{{font-family:'Helvetica Neue',Arial,sans-serif;color:#1c1e21;line-height:1.5;max-width:900px;margin:0 auto;padding:24px}}
 h1{{font-size:26px;border-bottom:3px solid #1c6;padding-bottom:6px;margin-top:40px}}
 h2{{font-size:21px;color:#0a4;border-bottom:1px solid #cce;margin-top:28px}}
 h3{{font-size:18px}}
 h4.card{{font-size:15px;background:#f3f6fb;padding:6px 10px;border-left:4px solid #1c6;margin-top:18px;page-break-after:avoid}}
 blockquote{{color:#555;border-left:3px solid #ccd;padding-left:12px;font-style:italic}}
 ul{{margin:6px 0 12px 0}} li{{margin:2px 0}}
 li.warn{{background:#fff3cd;border-left:3px solid #e0a800;padding:3px 8px;border-radius:4px;list-style:none;margin-left:-20px}}
 .photos{{display:flex;flex-wrap:wrap;gap:10px;margin:8px 0}}
 figure{{margin:0;text-align:center}} figure img{{max-width:240px;max-height:300px;border-radius:6px;border:1px solid #ddd}}
 figcaption{{font-size:11px;color:#777;max-width:240px}}
 table{{border-collapse:collapse;margin:10px 0;font-size:13px}} th,td{{border:1px solid #ccd;padding:4px 8px}} th{{background:#eef}}
 pre.mermaid{{background:#fafcff;border:1px solid #e3e9f5;border-radius:6px;padding:8px;page-break-inside:avoid;text-align:center}}
 a{{color:#1558b0;word-break:break-all}} @page{{size:A4;margin:14mm}}
</style></head><body>
{''.join(out)}
<script type="module">
import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.esm.min.mjs';
mermaid.initialize({{startOnLoad:false,securityLevel:'loose',maxEdges:2000,deterministicIds:true,flowchart:{{useMaxWidth:true}}}});
await mermaid.run({{querySelector:'pre.mermaid'}});
document.title='READY';
</script></body></html>"""
    open(html_path,"w",encoding="utf-8").write(HTML)
    print("HTML:",html_path,f"({len(HTML)//1024} КБ)")

if __name__=="__main__":
    build(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv)>3 else "Родословная")
