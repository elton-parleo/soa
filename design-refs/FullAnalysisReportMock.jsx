import { useState } from "react";

/* ─────────────────────────────────────────────────────────────────────────────
   FULL ANALYSIS REPORT — DESIGN MOCK · v5
   Matched to the SHIPPED audit report (screenshots), widget for widget:
   · AGENTIC VALUE SCORE hero — serif-italic blue accent word in the h1,
     icon pill tags, big score + blue "N points short" stat, horizontal
     lane row (lane width ∝ point budget, TV blue), share-of-mentions +
     modeled-exposure stat cards, three pillar cards w/ progress bars
     (TV = blue variant), "STRAIGHT SUM, NO BLACK BOX" sumline.
   · Pillar 01 widget — metric cards w/ icon titles, sentence body, dark
     bars, "＋ How it's scored" buttons, auto-selected competitor set w/
     hatched what-if extension + ILLUSTRATIVE footnote. EXTENDED with the
     funnel-stage selector: one graph, re-rendered per selected stage.
   · Pillar 03 widget — dark head (score + POINTS EARNED + Collapse),
     "YOUR PAGE, AS PARSED" SKU card (CAN QUOTE / CAN'T COUNT / INVISIBLE
     + source tags + merchant image column), "WHAT AGENTS COULD READ OF
     YOUR VALUE" six-signal list (live/stale + readability chips),
     dimension rows w/ ON YOUR SITE / IN ANSWERS duos, Value Protocols
     tsbox w/ check pills, "Why not agent-ready" note.
   Weights per the shipped report: V32 · A18 · TV50 · straight sum · ready 60.
   Sample: Allbirds vs Nike/Adidas/Vessi · numbers illustrative.
   ──────────────────────────────────────────────────────────────────────────── */

const CSS = `
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=IBM+Plex+Mono:wght@400;500;600&family=Instrument+Serif:ital@0;1&display=swap');
.fa{--canvas:#EFEEE9;--surface:#fff;--warm:#F7F6F2;--ink:#12141A;--text:#1A1D24;--muted:#6E7480;--faint:#9BA1AC;
--border:#E1DED7;--hairline:#E9E7E1;--strong:#CDC9C0;--blue:#2563EB;--blue-b:#3B7BFF;--blue-deep:#1B48C0;--blue-tint:#EDF2FE;--blue-soft:#CFDDFD;
--green:#1B7A46;--green-t:#E9F5ED;--amber:#A9741B;--amber-t:#FBF3E4;--red:#C0392B;--red-t:#FCEBE8;--dark:#151A24;
--sans:'Inter',system-ui,sans-serif;--mono:'IBM Plex Mono',monospace;--serif:'Instrument Serif',Georgia,serif;
font-family:var(--sans);color:var(--text);background:var(--canvas)}
.fa *{box-sizing:border-box;margin:0}
.page{display:grid;grid-template-columns:300px 1fr;max-width:1560px;margin:0 auto}
.rail{padding:26px 24px;position:sticky;top:0;height:100vh;align-self:start;overflow:auto;border-right:1px solid #E4E2DC}
.rlogo{display:flex;align-items:center;gap:9px;font-weight:700;font-size:16px;color:var(--ink)}
.rlogo .m{color:var(--blue);letter-spacing:-2px}
.ml{font-family:var(--mono);font-size:10px;letter-spacing:.14em;text-transform:uppercase;color:var(--faint)}
.rcard{background:#fff;border:1px solid var(--hairline);border-radius:18px;padding:22px 20px;margin:18px 0}
.bn{font-weight:700;font-size:15px;color:var(--ink)}
.rscore{font-size:44px;font-weight:700;letter-spacing:-.03em;color:var(--ink)}
.rbar{height:9px;border-radius:6px;background:#EDEBE5;margin:14px 0 8px;position:relative;overflow:hidden}
.rbar .f{position:absolute;inset:0;width:47%;background:var(--ink);border-radius:6px}
.rbar .rd{position:absolute;top:-2px;bottom:-2px;left:60%;width:2px;background:var(--amber)}
.rleg{display:flex;justify-content:space-between;font-family:var(--mono);font-size:9.5px;letter-spacing:.08em;color:var(--faint)}
.rrow{display:flex;align-items:center;gap:9px;font-size:14px;padding:6px 0}
.rrow .sw{width:10px;height:10px;border-radius:3px;flex:none}
.rrow .nm{flex:1;color:var(--text)}
.rrow .v{font-family:var(--mono);font-size:12.5px;font-weight:600;color:var(--ink)}
.chip{display:inline-flex;align-items:center;gap:6px;border-radius:999px;padding:6px 13px;font-size:13px;font-weight:500}
.chip.green{background:var(--green-t);color:var(--green)}
.chip.red{background:var(--red-t);color:var(--red)}
.chip.dot::before{content:'';width:7px;height:7px;border-radius:99px;background:currentColor}
.rnavhead{display:flex;justify-content:space-between;font-family:var(--mono);font-size:11px;letter-spacing:.12em;color:var(--faint);margin:20px 0 10px}
.rni{display:flex;align-items:center;gap:10px;padding:8px 10px;border-radius:10px;font-size:13.5px;color:var(--text);cursor:pointer}
.rni:hover{background:#E9E7E1}
.rni .i{font-family:var(--mono);width:16px;color:var(--muted)}
.rni .v{margin-left:auto;font-family:var(--mono);font-size:11px;color:var(--faint)}
.main{padding:26px 40px 90px;min-width:0}
/* ── hero (matches shipped AGENTIC VALUE SCORE widget) ── */
.hero{background:linear-gradient(150deg,#181D28,#12161F 60%);border-radius:26px;padding:34px 38px;color:#fff;margin-bottom:18px}
.hero .top{display:flex;justify-content:space-between;align-items:center;margin-bottom:26px;flex-wrap:wrap;gap:10px}
.hero .hl{display:flex;align-items:center;gap:9px;font-family:var(--mono);font-size:11px;letter-spacing:.14em;color:#AEB6C4}
.hero .hl .lg{color:var(--blue-b)}
.tags{display:flex;gap:9px;flex-wrap:wrap}
.tag{display:inline-flex;align-items:center;gap:8px;font-family:var(--mono);font-size:11px;letter-spacing:.1em;background:rgba(255,255,255,.07);border-radius:999px;padding:9px 16px;color:#E8EAEF}
h1.fa-h1{font-size:52px;font-weight:800;letter-spacing:-.035em;line-height:1.06;max-width:820px;color:#fff}
h1.fa-h1 em{font-family:var(--serif);font-style:italic;font-weight:400;color:var(--blue-b)}
h2.fa-h2{font-size:30px;font-weight:700;letter-spacing:-.025em;line-height:1.15;color:var(--ink)}
.verdict{display:flex;justify-content:flex-end;margin-top:-10px}
.verdict .chip{background:#FBE9E7;color:var(--red)}
.panel{background:rgba(255,255,255,.045);border:1px solid rgba(255,255,255,.09);border-radius:20px;padding:28px 30px;margin-top:22px}
.panel .prow{display:flex;justify-content:space-between;align-items:flex-start;gap:18px;flex-wrap:wrap}
.bignum{font-size:74px;font-weight:800;letter-spacing:-.04em;line-height:1;color:#fff}
.bignum small{font-size:26px;color:#6C7482;font-weight:600}
.short{text-align:right}
.short .v{font-size:26px;font-weight:700;color:var(--blue-b)}
.short .k{font-family:var(--mono);font-size:10px;letter-spacing:.12em;color:#6C7482;margin-top:4px}
.lanecard{background:#F6F5F1;border-radius:16px;padding:22px 24px;margin-top:24px;color:var(--text)}
.lh{display:flex;justify-content:space-between;margin-bottom:16px;flex-wrap:wrap;gap:8px}
.lanes{display:flex;gap:22px}
.lane .nm{font-size:14px;font-weight:600;color:var(--ink);margin-bottom:8px}
.lane .nm.tv{color:var(--blue)}
.track{height:36px;border-radius:8px;background:#fff;border:1px solid var(--border);position:relative;overflow:hidden;display:flex;align-items:center;justify-content:flex-end}
.track .fill{position:absolute;left:0;top:0;bottom:0;background:var(--ink)}
.track.tv .fill{background:var(--blue)}
.track span{position:relative;font-family:var(--mono);font-size:13px;font-weight:700;color:var(--ink);padding-right:12px}
.track span small{color:var(--faint);font-weight:500}
.pace{font-family:var(--mono);font-size:10.5px;letter-spacing:.08em;margin-top:9px}
.pace.ok{color:var(--green)}.pace.bad{color:var(--red)}
.statrow{display:grid;grid-template-columns:1fr 1fr;gap:18px;margin-top:18px}
.stat{background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.08);border-radius:18px;padding:22px 24px}
.stat.b{background:rgba(59,123,255,.08);border:1px solid rgba(59,123,255,.4)}
.stat .k{font-family:var(--mono);font-size:10px;letter-spacing:.12em;color:#8B93A1}
.stat .v{font-size:26px;font-weight:700;color:#fff;margin-top:8px}
.stat .s{font-size:13.5px;color:#8B93A1;margin-top:5px}
.stat .lk{color:var(--blue-b);font-size:13.5px;font-weight:600;margin-top:8px;display:inline-block}
.pcards{display:grid;grid-template-columns:repeat(3,1fr);gap:18px;margin-top:18px}
.pc{background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.08);border-radius:18px;padding:20px 22px}
.pc.tv{background:rgba(59,123,255,.07);border-color:rgba(59,123,255,.45)}
.pc .k{display:flex;align-items:center;gap:8px;font-size:14.5px;font-weight:600;color:#E8EAEF}
.pc .v{font-size:34px;font-weight:800;color:#fff;margin:10px 0 8px}
.pc .v small{font-size:15px;color:#6C7482;font-weight:600}
.pc .pb{height:4px;border-radius:4px;background:rgba(255,255,255,.14);overflow:hidden;margin-bottom:12px}
.pc .pb i{display:block;height:100%;background:#9BA1AC}
.pc.tv .pb i{background:var(--blue-b)}
.pc .c{font-family:var(--mono);font-size:9.5px;letter-spacing:.1em;color:#8B93A1;line-height:1.7}
.pc.tv .c{color:#9DBCFF}
.sumline{font-family:var(--mono);font-size:10.5px;letter-spacing:.1em;color:#6C7482;margin-top:24px;border-top:1px solid rgba(255,255,255,.08);padding-top:20px}
/* ── shared card grammar ── */
.card{background:var(--surface);border:1px solid var(--hairline);border-radius:22px;padding:30px 32px;margin-bottom:18px}
.sh{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;flex-wrap:wrap}
.sh .r{display:flex;align-items:center;gap:14px}
.sc{font-family:var(--mono);font-size:22px;font-weight:600;color:var(--ink)}
.sc small{font-size:13px;color:var(--faint);font-weight:500}
.collapse{display:inline-flex;align-items:center;gap:9px;border:1px solid var(--border);background:#fff;border-radius:14px;padding:10px 16px;font-size:15px;cursor:pointer;color:var(--text)}
.collapse .ic{width:22px;height:22px;border-radius:99px;background:var(--blue-tint);color:var(--blue);display:inline-flex;align-items:center;justify-content:center;font-size:12px}
.collapse.dk{background:rgba(255,255,255,.08);border-color:rgba(255,255,255,.16);color:#fff}
.how{display:inline-flex;align-items:center;gap:9px;border:1px solid var(--border);background:#fff;border-radius:14px;padding:9px 15px;font-size:14px;cursor:pointer;color:var(--text)}
.how .ic{width:22px;height:22px;border-radius:7px;background:var(--blue-tint);color:var(--blue);display:inline-flex;align-items:center;justify-content:center;font-size:13px}
.how.grey{background:#EFEDE7;border-color:#EFEDE7;font-family:var(--mono);font-size:11px;letter-spacing:.08em}
.steps{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-top:22px}
.step{border:1px solid var(--border);border-radius:16px;padding:18px 20px;background:#fff}
.step.good{border-color:#CDE4D6}
.step .k{font-family:var(--mono);font-size:10px;letter-spacing:.1em;color:var(--faint);display:block;margin-bottom:8px}
.step .v{font-size:14.5px;line-height:1.45}
.verdictnote{background:var(--warm);border:1px solid var(--hairline);border-radius:16px;padding:18px 20px;margin-top:22px;font-size:14.5px;color:var(--muted)}
.verdictnote b{color:var(--ink)}
/* ── pillar 01 (matches shipped widget) ── */
.metrics{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-top:22px}
.metric{background:var(--warm);border:1px solid var(--hairline);border-radius:16px;padding:20px 22px}
.metric .mh{display:flex;justify-content:space-between;align-items:baseline}
.metric .mh .t{display:flex;align-items:center;gap:9px;font-size:15.5px;font-weight:700;color:var(--ink)}
.metric .mh .t .gi{color:var(--blue)}
.metric .mh .v{font-family:var(--mono);font-size:17px;font-weight:600;color:var(--ink)}
.metric .mh .v small{font-size:12px;color:var(--faint)}
.metric .bd{font-size:14.5px;color:var(--text);line-height:1.55;margin-top:10px}
.mbar{height:10px;border-radius:6px;background:#E7E5DF;overflow:hidden;position:relative;margin:16px 0 8px}
.mbar i{display:block;height:100%;background:var(--ink)}
.mlegend{display:flex;justify-content:space-between;font-family:var(--mono);font-size:10px;letter-spacing:.08em;color:var(--muted);margin-bottom:14px}
.comps{margin-top:26px;border-top:1px solid var(--hairline);padding-top:22px}
.compshead{display:flex;justify-content:space-between;margin-bottom:10px;align-items:center;flex-wrap:wrap;gap:8px}
.comprow{display:flex;align-items:center;gap:16px;padding:9px 0;font-size:16px}
.comprow .av{width:26px;height:26px;border-radius:7px;background:#F1EFE9;color:var(--muted);display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:700;flex:none;font-family:var(--mono)}
.comprow.you .av{background:var(--blue);color:#fff}
.comprow .nm{width:120px;font-weight:500;color:var(--text)}
.comprow.you .nm{font-weight:700;color:var(--ink)}
.comprow .bar{flex:1;height:22px;border-radius:8px;background:#EFEDE7;position:relative;overflow:hidden}
.comprow .bar i{position:absolute;left:0;top:0;bottom:0;border-radius:8px;background:#C9C5BC}
.comprow.you .bar i{background:var(--blue)}
.comprow.you .bar .wf{position:absolute;top:0;bottom:0;background:repeating-linear-gradient(45deg,var(--blue-tint),var(--blue-tint) 4px,var(--blue-soft) 4px,var(--blue-soft) 8px);border:1px dashed var(--blue);border-left:none;border-radius:0 8px 8px 0}
.comprow .pct{font-family:var(--mono);font-size:13px;width:60px;text-align:right;color:var(--muted);font-weight:600}
.comprow.you .pct{color:var(--blue)}
.fatabs{display:flex;gap:4px;flex-wrap:wrap}
.fatab{font-family:var(--mono);font-size:10px;letter-spacing:.1em;text-transform:uppercase;padding:9px 14px;border:1px solid var(--border);background:#fff;cursor:pointer;color:var(--muted);border-radius:999px}
.fatab.on{color:#fff;background:var(--ink);border-color:var(--ink)}
/* ── pillar 03 (matches shipped tv widget) ── */
.tvcard{background:var(--surface);border:1.5px solid var(--blue);border-radius:24px;margin-bottom:18px;overflow:hidden}
.tvhead{background:linear-gradient(150deg,#181D28,#12161F);color:#fff;padding:30px 32px}
.tvhead .top{display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:10px}
.tvhead .lft{display:flex;align-items:center;gap:12px;flex-wrap:wrap}
.tvhead h2{color:#fff;margin-top:14px;max-width:700px}
.tvhead .sub{color:#8B93A1;font-size:14.5px;margin-top:10px;max-width:700px;line-height:1.6}
.tvhead .pts{text-align:right}
.tvhead .pts .v{font-size:40px;font-weight:800}
.tvhead .pts .v small{font-size:17px;color:#6C7482}
.mchip{display:inline-flex;align-items:center;gap:6px;font-family:var(--mono);font-size:10px;letter-spacing:.1em;border-radius:999px;padding:6px 12px}
.mchip.grey{background:#EFEDE7;color:var(--muted)}
.mchip.blue{background:var(--blue);color:#fff}
.mchip.bluet{background:var(--blue-tint);color:var(--blue-deep);border:1px solid var(--blue-soft)}
.mchip.green{background:var(--green-t);color:var(--green)}
.mchip.amber{background:var(--amber-t);color:var(--amber)}
.mchip.red{background:var(--red-t);color:var(--red)}
.tvbody{background:#fff;padding:30px 32px}
.parsed{background:var(--warm);border:1px solid var(--hairline);border-radius:18px;padding:24px 26px;display:grid;grid-template-columns:1fr 200px;gap:26px}
.parsed .pn{font-size:17px;font-weight:700;color:var(--ink);margin:12px 0 8px}
.parsed .pp{display:flex;align-items:center;gap:12px}
.parsed .pp .pr{font-family:var(--mono);font-size:22px;font-weight:600;color:var(--ink)}
.pgroup{margin-top:18px;border-top:1px solid var(--hairline);padding-top:14px}
.pgl{font-family:var(--mono);font-size:10px;letter-spacing:.12em;margin-bottom:10px;display:flex;align-items:center;gap:8px}
.pgl.g{color:var(--green)}.pgl.a{color:var(--amber)}.pgl.r{color:var(--red)}
.prowi{display:flex;justify-content:space-between;align-items:center;border-radius:10px;padding:11px 14px;font-size:14px;margin-bottom:8px;background:#fff}
.prowi.a{background:var(--amber-t)}
.prowi.r{background:var(--red-t)}
.prowi .src{font-family:var(--mono);font-size:9.5px;letter-spacing:.1em;color:var(--faint)}
.pimg{display:flex;flex-direction:column;gap:10px}
.pimg .ib{background:#fff;border:1px solid var(--hairline);border-radius:14px;height:170px;display:flex;align-items:center;justify-content:center;color:var(--faint)}
.pimg .cap{font-size:12.5px;color:var(--muted);line-height:1.55}
.sigcard{background:var(--warm);border:1px solid var(--hairline);border-radius:18px;padding:22px 26px;margin-top:18px}
.sigrow{display:flex;align-items:center;gap:16px;padding:14px 0;border-bottom:1px solid var(--hairline)}
.sigrow:last-child{border-bottom:none}
.sigrow .si{width:36px;height:36px;border-radius:11px;background:#EFEDE7;color:var(--muted);display:flex;align-items:center;justify-content:center;font-size:15px;flex:none}
.sigrow.hot .si{background:var(--blue-tint);color:var(--blue)}
.sigrow .sn{flex:1}
.sigrow .sn .t{font-size:15px;font-weight:700;color:var(--ink)}
.sigrow .sn .t em{font-style:normal;color:var(--green);font-weight:600;margin-left:8px}
.sigrow .sn .u{font-family:var(--mono);font-size:10px;letter-spacing:.1em;color:var(--faint);margin-top:4px}
.sigrow .chips{display:flex;gap:8px;flex-wrap:wrap}
.dimrow{padding:24px 0;border-top:1px solid var(--hairline)}
.dh{display:flex;align-items:center;gap:12px;flex-wrap:wrap}
.dh .gi{color:var(--ink)}
.dh .nm{font-size:17px;font-weight:700;color:var(--ink)}
.dh .sc{font-size:16px}
.dh .tl{font-size:14.5px;color:var(--muted);flex:1 1 220px}
.dh .rt{margin-left:auto}
.duo{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-top:16px}
.dbox{background:var(--warm);border:1px solid var(--hairline);border-radius:16px;padding:18px 20px}
.dbox .k{display:flex;justify-content:space-between;align-items:center;font-family:var(--mono);font-size:10px;letter-spacing:.1em;color:var(--muted);margin-bottom:12px}
.dbox .k .v{font-size:15px;font-weight:600;color:var(--ink)}
.dbox .k .v small{color:var(--faint);font-weight:500}
.tsbox{border:1.5px solid var(--blue);background:var(--blue-tint);border-radius:18px;padding:22px 24px;margin-top:24px}
.tsbox .h{display:flex;align-items:center;gap:14px;flex-wrap:wrap}
.tsbox .h .t{font-size:17px;font-weight:700;color:var(--ink)}
.tsbox .h .v{font-family:var(--mono);font-size:15px;font-weight:600}
.tsbox .h .rt{margin-left:auto}
.pills{display:flex;flex-wrap:wrap;gap:8px;margin-top:16px;padding-bottom:16px;border-bottom:1px solid var(--blue-soft)}
.pill{font-family:var(--mono);font-size:11px;border-radius:999px;padding:8px 13px}
.pill.r{background:var(--red-t);color:var(--red)}
.pill.g{background:var(--green-t);color:var(--green)}
.tsbox .d{font-size:14.5px;color:var(--text);margin-top:14px;line-height:1.65}
/* ── rest ── */
.finding{padding:34px 6px 22px}
.finding h2{font-size:34px;max-width:860px;margin-top:10px}
.finding .sub{font-size:15.5px;color:var(--muted);margin-top:10px;max-width:760px;line-height:1.65}
.mx{width:100%;border-collapse:collapse;margin-top:22px;font-size:14px}
.mx th{font-family:var(--mono);font-size:9.5px;letter-spacing:.1em;text-transform:uppercase;color:var(--faint);font-weight:500;text-align:left;padding:8px 12px}
.mx .gh th{font-size:10px;color:var(--muted);border-bottom:2px solid var(--strong);padding-top:0}
.mx .gh th.tvg{color:var(--blue);border-bottom-color:var(--blue)}
.mx td{padding:12px 12px;border-top:1px solid var(--hairline)}
.mx td.p{font-weight:600;color:var(--ink)}
.mx .mono{font-family:var(--mono);font-size:12.5px}
.minibar{display:inline-block;width:52px;height:7px;border-radius:5px;background:#E7E5DF;position:relative;vertical-align:middle;margin-right:9px}
.minibar i{position:absolute;inset:0;border-radius:5px;background:var(--muted)}
.editorial{font-family:var(--serif);font-style:italic;font-size:34px;line-height:1.3;color:#B3B0A8}
.fixhead{display:grid;grid-template-columns:40px 1fr 150px 120px;gap:18px;font-family:var(--mono);font-size:9.5px;letter-spacing:.12em;color:var(--faint);text-transform:uppercase;padding:18px 0 10px;border-bottom:1px solid var(--hairline)}
.fixrow{display:grid;grid-template-columns:40px 1fr 150px 120px;gap:18px;align-items:center;padding:18px 0;border-bottom:1px solid var(--hairline)}
.fixrow:last-of-type{border-bottom:none}
.fixrow .n{font-family:var(--mono);font-size:15px;color:var(--faint)}
.fixrow .t{font-weight:600;font-size:15.5px;color:var(--ink)}
.fixrow .d{font-size:13px;color:var(--muted);margin-top:4px;line-height:1.6}
.fixrow .p{font-family:var(--mono);font-size:19px;font-weight:600;color:var(--green)}
.own{font-family:var(--mono);font-size:10px;letter-spacing:.1em;border:1px solid var(--border);border-radius:999px;padding:6px 12px;text-align:center;color:var(--muted)}
.own.t{border-color:var(--blue);color:var(--blue-deep);background:var(--blue-tint)}
.six{width:100%;border-collapse:collapse;font-size:13.5px;margin-top:18px}
.six th{font-family:var(--mono);font-size:9.5px;letter-spacing:.1em;text-transform:uppercase;color:var(--faint);text-align:left;padding:12px 10px;font-weight:500}
.six td{padding:12px 10px;border-top:1px solid var(--hairline)}
.six td.m{font-weight:600;color:var(--ink)}
.six .mono{font-family:var(--mono);font-size:12.5px;color:var(--muted)}
.six .you{color:var(--ink);font-weight:600}
.quote{background:var(--warm);border:1px solid var(--hairline);border-radius:16px;padding:20px 24px;font-size:14.5px;line-height:1.75;color:var(--text);margin-top:18px}
.quote mark.bad{background:var(--red-t);color:var(--red);padding:1px 4px;border-radius:3px}
.quote mark.riv{background:#EFEDE7;color:var(--text);padding:1px 4px;border-radius:3px}
.coding{margin-top:14px;font-family:var(--mono);font-size:12px;color:#9BA1AC;background:#12161F;border-radius:12px;padding:16px 20px;line-height:1.9}
.coding b{color:#7FA6FF;font-weight:500}
.coding .bad{color:#E08579}
.dband{background:linear-gradient(150deg,#181D28,#12161F);border-radius:24px;padding:32px 34px;color:#fff;margin-bottom:18px;display:flex;justify-content:space-between;align-items:center;gap:20px;flex-wrap:wrap}
.dband h2{color:#fff;max-width:560px}
.dband .b{background:var(--blue);color:#fff;border:none;border-radius:12px;padding:14px 22px;font-size:14.5px;font-weight:600;cursor:pointer;font-family:var(--sans)}
.foot{font-family:var(--mono);font-size:10.5px;letter-spacing:.08em;color:var(--faint);line-height:2;padding:10px 6px 40px}
@media(max-width:1000px){.page{grid-template-columns:1fr}.rail{position:static;height:auto;border-right:none}.pcards,.steps{grid-template-columns:1fr}.metrics,.duo,.statrow{grid-template-columns:1fr}.lanes{flex-direction:column}.lane{width:100%!important}h1.fa-h1{font-size:36px}.parsed{grid-template-columns:1fr}.fixhead,.fixrow{grid-template-columns:32px 1fr 90px}}
`;

/* V32 · A18 · TV50 — the shipped rubric */
const PIL = [
  { g: "◉", name: "Visibility", earned: 17, max: 32, sw: "#12141A", pace: "ok", paceTx: "● AT PACE", cap: "AGENTS KNOW WHO YOU ARE" },
  { g: "◎", name: "Accessibility", earned: 11, max: 18, sw: "#6E7480", pace: "ok", paceTx: "● AT PACE", cap: "TWO OF FIVE AGENTS CAN'T CRAWL YOU" },
  { g: "◇", name: "True Value", earned: 19, max: 50, sw: "#2563EB", pace: "bad", paceTx: "● -11 TO PACE", cap: "YOUR OFFERS NEVER SURVIVE INTO ANSWERS ON ANY OF 5 PLATFORMS." },
];

const MATRIX = [
  { p: "ChatGPT", som: 27, rec: "NAMED PICK", recCls: "green", access: true, price: 61, cite: 12, member: "cited, no price" },
  { p: "Perplexity", som: 24, rec: "SHORTLISTED", recCls: "grey", access: false, price: 48, cite: 21, member: "never cited" },
  { p: "Gemini", som: 22, rec: "SHORTLISTED", recCls: "grey", access: true, price: 55, cite: 8, member: "never cited" },
  { p: "Claude", som: 26, rec: "NAMED PICK", recCls: "green", access: true, price: 64, cite: 14, member: "cited, no price" },
  { p: "Copilot", som: 19, rec: "MENTIONED", recCls: "grey", access: false, price: 51, cite: 6, member: "never cited" },
];

/* competitor shares: overall + per stage — one graph, selector-driven */
const STAGE_DATA = {
  "All stages": [["Allbirds", "A", 24, true], ["Nike", "N", 46], ["Adidas", "AD", 21], ["Vessi", "V", 9]],
  "Awareness": [["Allbirds", "A", 34, true], ["Nike", "N", 41], ["Adidas", "AD", 18], ["Vessi", "V", 7]],
  "Research": [["Allbirds", "A", 29, true], ["Nike", "N", 44], ["Adidas", "AD", 19], ["Vessi", "V", 8]],
  "Comparison": [["Allbirds", "A", 22, true], ["Nike", "N", 49], ["Adidas", "AD", 21], ["Vessi", "V", 8]],
  "Ready to Buy": [["Allbirds", "A", 15, true], ["Nike", "N", 55], ["Adidas", "AD", 24], ["Vessi", "V", 6]],
};

const SIX = [
  ["Mention Rate", "70%", "89%", "61%", "28%"],
  ["Share of Mentions", "24%", "46%", "21%", "9%"],
  ["Recommendation Strength", "0.53", "0.71", "0.48", "0.31"],
  ["Position Index", "2.4", "1.6", "2.9", "3.8"],
  ["Platform Distribution", "0.82", "0.97", "0.79", "0.44"],
  ["Incentive Citation Rate", "12%", "20%", "9%", "4%"],
];

export default function FullAnalysisReportMock() {
  const [stage, setStage] = useState("All stages");
  const [tab, setTab] = useState("Overall");
  const [coding, setCoding] = useState(false);
  const rows = STAGE_DATA[stage];
  const sorted = [...rows].sort((a, b) => b[2] - a[2]);
  const rank = sorted.findIndex((r) => r[3]) + 1;
  return (
    <div className="fa">
      <style>{CSS}</style>
      <div className="page">

        {/* rail */}
        <aside className="rail">
          <div className="rlogo"><span className="m">▮▮</span> Parleo</div>
          <div className="ml" style={{ marginTop: 6 }}>Full Agentic Value Analysis</div>
          <div className="rcard">
            <div className="bn">Allbirds</div>
            <div className="ml" style={{ margin: "2px 0 10px" }}>allbirds.com · vs 3 competitors</div>
            <div className="rscore">47</div>
            <div className="rbar"><div className="f" /><div className="rd" /></div>
            <div className="rleg"><span>47 EARNED</span><span>READY 60</span><span>100</span></div>
            <div style={{ marginTop: 12 }}>
              {PIL.map((p) => (
                <div className="rrow" key={p.name}>
                  <span className="sw" style={{ background: p.sw }} />
                  <span className="nm">{p.name}</span>
                  <span className="v">{p.earned}/{p.max}</span>
                </div>
              ))}
            </div>
            <div style={{ marginTop: 12 }}><span className="chip green dot">Fully measured</span></div>
            <div className="ml" style={{ marginTop: 10 }}>EVERY POINT READ THIS RUN</div>
          </div>
          <div className="rnavhead"><span>IN THIS REPORT</span><span>10</span></div>
          {[["▮", "The score", "47/100"], ["◍", "Vs. your audit", "▲6"], ["⌕", "Discovery", "4/4"], ["⊞", "Platform matrix", "5×6"], ["◉", "Visibility", "17/32"], ["◎", "Accessibility", "11/18"], ["◇", "True Value", "19/50"], ["✓", "Ranked fixes", "+19"], ["↻", "TrueSync", ""], ["▤", "Exposure", "$412K"]].map(([i, t, v]) => (
            <div className="rni" key={t}><span className="i">{i}</span>{t}<span className="v">{v}</span></div>
          ))}
        </aside>

        <main className="main">

          {/* ── AGENTIC VALUE SCORE — the shipped hero, full-analysis content ── */}
          <section className="hero">
            <div className="top">
              <span className="hl"><span className="lg">▮▮</span> AGENTIC VALUE SCORE</span>
              <span className="tags">
                <span className="tag">◎ 5 PLATFORMS</span>
                <span className="tag">50 QUERIES</span>
                <span className="tag">1,250 ANSWERS</span>
              </span>
            </div>
            <h1 className="fa-h1">Agents know you. Your best price is <em>invisible.</em></h1>
            <div className="verdict"><span className="chip dot">Not agent-ready</span></div>
            <div className="panel">
              <div className="prow">
                <div className="bignum">47 <small>/100</small></div>
                <div className="short">
                  <div className="v">13 points</div>
                  <div className="k">SHORT OF THE READINESS BAR</div>
                </div>
              </div>
              <div className="lanecard">
                <div className="lh">
                  <span className="ml">LANE WIDTH = POINT BUDGET · FILL = POINTS EARNED</span>
                  <span className="ml">PACE FOR A READY SCORE</span>
                </div>
                <div className="lanes">
                  {PIL.map((p) => (
                    <div className="lane" key={p.name} style={{ width: p.max + "%", flexGrow: p.max }}>
                      <div className={"nm" + (p.g === "◇" ? " tv" : "")}>{p.name}</div>
                      <div className={"track" + (p.g === "◇" ? " tv" : "")}>
                        <div className="fill" style={{ width: (p.earned / p.max) * 100 + "%" }} />
                        <span>{p.earned}<small>/{p.max}</small></span>
                      </div>
                      <div className={"pace " + p.pace}>{p.paceTx}</div>
                    </div>
                  ))}
                </div>
              </div>
              <div className="statrow">
                <div className="stat">
                  <div className="k">◉ SHARE OF MENTIONS</div>
                  <div className="v">2nd of 4</div>
                  <div className="s">In your auto-selected competitor set — Nike leads at 46%</div>
                </div>
                <div className="stat b">
                  <div className="k">▤ MODELED EXPOSURE / YEAR</div>
                  <div className="v">$412,000</div>
                  <span className="lk">How we model this →</span>
                </div>
              </div>
              <div className="pcards">
                {PIL.map((p) => (
                  <div className={"pc" + (p.g === "◇" ? " tv" : "")} key={p.name}>
                    <div className="k">{p.g} {p.name}</div>
                    <div className="v">{p.earned} <small>/{p.max}</small></div>
                    <div className="pb"><i style={{ width: (p.earned / p.max) * 100 + "%" }} /></div>
                    <div className="c">{p.cap}</div>
                  </div>
                ))}
              </div>
              <div className="sumline">VISIBILITY 32 · ACCESSIBILITY 18 · TRUE VALUE 50 · STRAIGHT SUM, NO BLACK BOX</div>
            </div>
          </section>

          {/* continuation */}
          <section className="tsbox" style={{ marginTop: 0, marginBottom: 18, display: "flex", alignItems: "center", gap: 24, flexWrap: "wrap", borderWidth: 1.5 }}>
            <div style={{ flex: "1 1 360px" }}>
              <span className="mchip bluet">◍ CONTINUED FROM YOUR AUDIT · JUL 28</span>
              <div className="d" style={{ marginTop: 10 }}>
                Your free audit (ChatGPT · 24 questions) scored <b style={{ fontFamily: "var(--mono)" }}>41</b>. This analysis re-measures the same rubric across 5 platforms, 4 funnel stages, and 3 personas — 52× the evidence.
              </div>
            </div>
            {[["Visibility", "▲ 3.1 PTS", true], ["Accessibility", "= FLAT", false], ["True Value", "▲ 2.7 PTS", true]].map(([n, d, up]) => (
              <div key={n} style={{ textAlign: "center" }}>
                <div className="ml">{n}</div>
                <div style={{ fontFamily: "var(--mono)", fontSize: 12.5, fontWeight: 600, marginTop: 4, color: up ? "var(--green)" : "var(--muted)" }}>{d}</div>
              </div>
            ))}
          </section>

          {/* headline finding */}
          <section className="finding">
            <div className="ml">THE HEADLINE FINDING</div>
            <h2 className="fa-h2">You lose the funnel, not the shelf: 19 points of share vanish between Awareness and Ready-to-Buy.</h2>
            <div className="sub">Agents mention you constantly when shoppers browse — then quote resale prices, skip your three live promotions, and route purchase-ready shoppers to Nike. Parleo can fix 2 of your 4 gaps directly.</div>
          </section>

          {/* discovery */}
          <section className="card">
            <div className="sh">
              <div>
                <div className="ml">FINDING 00 · DISCOVERY · MEASURED</div>
                <h2 className="fa-h2" style={{ marginTop: 10 }}>This time, everything opened</h2>
              </div>
              <div className="r"><button className="collapse"><span className="ic">⌄</span> Collapse</button></div>
            </div>
            <div className="steps">
              <div className="step good"><span className="k">01 · ROBOTS.TXT</span><div className="v">Read fine. Product paths allowed for 4 of 6 agent crawlers.</div></div>
              <div className="step good"><span className="k">02 · HOMEPAGE</span><div className="v">Fetched fine — all five agents opened it during answers.</div></div>
              <div className="step good"><span className="k">03 · SITEMAPS</span><div className="v">6 resolved · 1,940 product URLs listed and fresh.</div></div>
              <div className="step good"><span className="k">04 · PRODUCT PAGES</span><div className="v">120 sampled, 120 parsed. What your audit couldn't read: read.</div></div>
            </div>
            <div className="verdictnote">The audit's partial read is closed — every scored claim below rests on pages we actually parsed and answers we actually coded.</div>
          </section>

          {/* platform matrix */}
          <section className="card">
            <div className="sh">
              <div>
                <div className="ml">⊞ THE MATRIX · 5 PLATFORMS × EVERY PILLAR DIMENSION</div>
                <h2 className="fa-h2" style={{ marginTop: 10 }}>Where the score comes from, agent by agent</h2>
              </div>
              <div className="r"><span className="ml">250 ANSWERS PER PLATFORM</span><button className="collapse"><span className="ic">⌄</span> Collapse</button></div>
            </div>
            <table className="mx">
              <thead>
                <tr className="gh"><th /><th colSpan={2}>◉ VISIBILITY</th><th colSpan={1}>◎ ACCESSIBILITY</th><th colSpan={3} className="tvg">◇ TRUE VALUE</th></tr>
                <tr><th>Platform</th><th>Share of mentions</th><th>Rec strength</th><th>Agent access</th><th>Price truth · said</th><th>Deal citability</th><th>Member value</th></tr>
              </thead>
              <tbody>
                {MATRIX.map((r) => (
                  <tr key={r.p}>
                    <td className="p">{r.p}</td>
                    <td className="mono"><span className="minibar"><i style={{ width: r.som * 2 + "%" }} /></span>{r.som}%</td>
                    <td><span className={"mchip " + r.recCls}>{r.rec}</span></td>
                    <td><span className={"mchip " + (r.access ? "green" : "red")}>{r.access ? "◉ ADMITTED" : "◌ BLOCKED"}</span></td>
                    <td className="mono" style={{ color: r.price < 55 ? "var(--red)" : "var(--text)" }}>{r.price}% accurate</td>
                    <td className="mono" style={{ color: r.cite < 10 ? "var(--red)" : "var(--text)" }}>{r.cite}% cited</td>
                    <td className="mono" style={{ color: r.member === "never cited" ? "var(--faint)" : "var(--text)" }}>{r.member}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="verdictnote">The two platforms whose crawlers you block are your two weakest on price accuracy. <b>Access and accuracy line up.</b></div>
          </section>

          {/* ── PILLAR 01 — the shipped widget, extended with the stage selector ── */}
          <section className="card">
            <div className="sh">
              <div>
                <div className="ml">PILLAR 01 · VISIBILITY · 1,250 ANSWERS</div>
                <h2 className="fa-h2" style={{ marginTop: 10 }}>Agents know who you are</h2>
              </div>
              <div className="r"><span className="sc">17<small>/32</small></span><button className="collapse"><span className="ic">⌄</span> Collapse</button></div>
            </div>
            <div className="metrics">
              <div className="metric">
                <div className="mh"><span className="t"><span className="gi">◉</span> Share of Mentions</span><span className="v">11<small>/22</small></span></div>
                <div className="bd">24% of all brand mentions were you. 50% share earns all 22 points.</div>
                <div className="mbar"><i style={{ width: "48%" }} /></div>
                <div className="mlegend"><span>YOU · 24%</span><span>50% EARNS ALL 22</span></div>
                <button className="how"><span className="ic">＋</span> How it's scored</button>
              </div>
              <div className="metric">
                <div className="mh"><span className="t"><span className="gi">☆</span> Recommendation Strength</span><span className="v">6<small>/10</small></span></div>
                <div className="bd">Where you land when agents do mention you: a named pick on 2 of 5 platforms.</div>
                <div className="mbar"><i style={{ width: "60%" }} /></div>
                <div className="mlegend"><span>NAMED PICK · 2 OF 5 PLATFORMS</span><span>TOP BAND EARNS ALL 10</span></div>
                <button className="how"><span className="ic">＋</span> How it's scored</button>
              </div>
            </div>
            {/* competitor set — one graph, stage-driven */}
            <div className="comps">
              <div className="compshead">
                <span className="ml">◈ YOUR AUTO-SELECTED COMPETITOR SET</span>
                <span className="ml">{rank === 1 ? "1ST" : rank === 2 ? "2ND" : rank === 3 ? "3RD" : rank + "TH"} OF {rows.length}{stage !== "All stages" ? " · " + stage.toUpperCase() : ""}</span>
              </div>
              <div className="fatabs" style={{ margin: "6px 0 14px" }}>
                {Object.keys(STAGE_DATA).map((s) => (
                  <button key={s} className={"fatab" + (s === stage ? " on" : "")} onClick={() => setStage(s)}>{s}</button>
                ))}
              </div>
              {sorted.map(([nm, av, pct, you]) => (
                <div className={"comprow" + (you ? " you" : "")} key={nm}>
                  <span className="av">{av}</span>
                  <span className="nm">{nm}</span>
                  <span className="bar">
                    <i style={{ width: pct * 1.7 + "%" }} />
                    {you && stage === "Ready to Buy" && <span className="wf" style={{ left: pct * 1.7 + "%", width: "14%" }} />}
                  </span>
                  <span className="pct">{pct}%</span>
                </div>
              ))}
              <div className="ml" style={{ marginTop: 12 }}>
                {stage === "Ready to Buy"
                  ? "▨ HATCH = ILLUSTRATIVE SHARE IF YOUR 3 LIVE OFFERS WERE CITABLE · NOT A FORECAST"
                  : "SWITCH STAGES TO SEE WHERE THE FUNNEL LEAKS · AWARENESS 34% → READY-TO-BUY 15%"}
              </div>
            </div>
          </section>

          {/* pillar 02 */}
          <section className="card">
            <div className="sh">
              <div>
                <div className="ml">PILLAR 02 · ACCESSIBILITY · CRAWLED AUG 9</div>
                <h2 className="fa-h2" style={{ marginTop: 10 }}>Four doors open, two agents still knock in vain</h2>
              </div>
              <div className="r"><span className="sc">11<small>/18</small></span><button className="collapse"><span className="ic">⌄</span> Collapse</button></div>
            </div>
            <div className="metrics">
              <div className="metric">
                <div className="mh"><span className="t"><span className="gi">◎</span> Agent access</span><span className="v">4<small>/8</small></span></div>
                <div className="bd">robots.txt admits 4 of 6 known agent crawlers — PerplexityBot and Copilot's crawler are blocked. See the matrix: your two blocked platforms score worst.</div>
                <button className="how" style={{ marginTop: 12 }}><span className="ic">＋</span> How it's scored</button>
              </div>
              <div className="metric">
                <div className="mh"><span className="t"><span className="gi">▤</span> Catalog, context & protocol</span><span className="v">7<small>/10</small></span></div>
                <div className="bd">Product schema on 87% of PDPs, sitemap fresh — but salePrice is missing on bundles, and nothing at your domain root (llms.txt, MCP, offers feed) declares you to agents.</div>
                <button className="how" style={{ marginTop: 12 }}><span className="ic">＋</span> How it's scored</button>
              </div>
            </div>
          </section>

          {/* ── PILLAR 03 — the shipped tv widget, full-read content ── */}
          <section className="tvcard">
            <div className="tvhead">
              <div className="top">
                <span className="lft">
                  <span className="ml" style={{ color: "#AEB6C4" }}>◇ PILLAR 03 · TRUE VALUE</span>
                  <span className="mchip blue">THE PILLAR ONLY PARLEO MEASURES</span>
                </span>
                <div className="pts">
                  <div className="v">19<small>/50</small></div>
                  <div className="ml" style={{ color: "#6C7482" }}>POINTS EARNED</div>
                  <button className="collapse dk" style={{ marginTop: 10 }}><span className="ic">⌄</span> Collapse</button>
                </div>
              </div>
              <h2 className="fa-h2">Your deals appear on 0 of 120 pages, while agents misquote your price on all 5 platforms.</h2>
              <div className="sub">One SKU, as parsed from the pages we read, next to what agents actually said in 1,250 answers. Every dimension measurable this run.</div>
            </div>
            <div className="tvbody">
              {/* YOUR PAGE, AS PARSED */}
              <div className="parsed">
                <div>
                  <span className="ml">▤ YOUR PAGE, AS PARSED</span>
                  <div className="pn">Men's Wool Runner</div>
                  <div className="pp"><span className="pr">$110.00</span><span className="mchip green">◉ InStock</span></div>
                  <div className="pgroup">
                    <div className="pgl g">✓ CAN QUOTE</div>
                    <div className="prowi"><span>Availability: InStock</span><span className="src">SCHEMA.ORG</span></div>
                  </div>
                  <div className="pgroup">
                    <div className="pgl a">≠ CAN'T COUNT</div>
                    <div className="prowi a"><span>List price: $110.00</span><span className="src">SCHEMA.ORG</span></div>
                    <div className="prowi a"><span>Shipping: free shipping</span><span className="src">PAGE COPY</span></div>
                    <div className="prowi a"><span>Deals and promos: Not encoded</span><span className="src">NONE</span></div>
                  </div>
                  <div className="pgroup">
                    <div className="pgl r">✕ INVISIBLE</div>
                    <div className="prowi r"><span>Member price: login-gated</span><span className="src">UNVERIFIABLE</span></div>
                    <div className="prowi r"><span>Checkout value: Nothing declared</span><span className="src">UCP / ACP</span></div>
                  </div>
                </div>
                <div className="pimg">
                  <div className="ib"><span className="ml">PRODUCT IMAGE</span></div>
                  <div className="cap">The merchant's own image, from the same markup we scored.</div>
                </div>
              </div>
              {/* WHAT AGENTS COULD READ OF YOUR VALUE */}
              <div className="sigcard">
                <div className="ml" style={{ marginBottom: 6 }}>WHAT AGENTS COULD READ OF YOUR VALUE</div>
                {[
                  ["List price", "$110.00", "SCHEMA.ORG, 118 OF 120 PAGES", "live", "Partial", false],
                  ["Availability", "InStock", "SCHEMA.ORG, 120 OF 120 PAGES", "live", "Agent-readable", true],
                  ["Shipping", "free shipping", "PAGE COPY, TEXT ONLY, NO STRUCTURED THRESHOLD", "live", "Partial", false],
                  ["Member price", "login-gated", "PRESENT, UNVERIFIABLE — 0 OF 120 PAGES", "stale", "Not readable", false],
                  ["Deals and promos", "3 live, not encoded", "BANNER COPY ONLY, 0 OF 120 PAGES", "stale", "Partial", false],
                  ["Checkout value", "Nothing declared", "UCP / ACP, NO DECLARATION FOUND", "stale", "Not readable", false],
                ].map(([t, v, u, live, read, hot]) => (
                  <div className={"sigrow" + (hot ? " hot" : "")} key={t}>
                    <span className="si">◇</span>
                    <span className="sn"><span className="t">{t} <em>{v}</em></span><div className="u">{u}</div></span>
                    <span className="chips">
                      <span className={"mchip " + (live === "live" ? "green" : "amber")}>● {live}</span>
                      <span className={"mchip " + (read === "Agent-readable" ? "green" : read === "Partial" ? "amber" : "red")}>{read === "Not readable" ? "◌" : "◉"} {read}</span>
                    </span>
                  </div>
                ))}
              </div>
              {/* dimensions */}
              <div className="dimrow" style={{ borderTop: "none", paddingTop: 28 }}>
                <div className="dh">
                  <span className="gi">▤</span><span className="nm">Price Truth</span><span className="sc">7<small>/16</small></span>
                  <span className="tl">readable on your site, cited in answers</span>
                  <span className="rt"><button className="how"><span className="ic">＋</span> How it's scored</button></span>
                </div>
                <div className="duo">
                  <div className="dbox">
                    <div className="k"><span>▤ ON YOUR SITE</span><span className="v">3<small>/7</small></span></div>
                    <div className="mbar"><i style={{ width: "43%" }} /></div>
                  </div>
                  <div className="dbox">
                    <div className="k"><span>◑ IN ANSWERS</span><span className="v">4<small>/9</small></span></div>
                    <div className="mbar"><i style={{ width: "58%" }} /></div>
                    <div style={{ fontSize: 13, color: "var(--muted)", marginTop: 8 }}>58% of 246 price statements match Deal Engine ground truth — the misses quote resale listings.</div>
                  </div>
                </div>
              </div>
              <div className="dimrow">
                <div className="dh">
                  <span className="gi">☆</span><span className="nm">Deal Citability</span><span className="sc">5<small>/12</small></span>
                  <span className="tl">deals encoded, cited when shoppers are ready</span>
                  <span className="rt"><button className="how"><span className="ic">＋</span> How it's scored</button></span>
                </div>
                <div className="duo">
                  <div className="dbox">
                    <div className="k"><span>▤ ON YOUR SITE</span><span className="v">0<small>/5</small></span></div>
                    <div className="mbar"><i style={{ width: "3%" }} /></div>
                    <div style={{ fontSize: 13, color: "var(--muted)", marginTop: 8 }}>3 live promotions, 0 in structured form.</div>
                  </div>
                  <div className="dbox">
                    <div className="k"><span>◑ IN ANSWERS</span><span className="v">5<small>/7</small></span></div>
                    <div className="mbar"><i style={{ width: "38%" }} /></div>
                    <div style={{ fontSize: 13, color: "var(--muted)", marginTop: 8 }}>Free shipping surfaces on 2 platforms; bundle and student offers never cited.</div>
                  </div>
                </div>
              </div>
              <div className="dimrow">
                <div className="dh">
                  <span className="gi">◈</span><span className="nm">Member Value</span><span className="sc">2<small>/8</small></span>
                  <span className="tl">program found and named — value never quantified</span>
                  <span className="rt"><button className="how"><span className="ic">＋</span> How it's scored</button></span>
                </div>
                <div className="duo">
                  <div className="dbox">
                    <div className="k"><span>▤ ON YOUR SITE</span><span className="mchip grey">LOGIN-GATED</span></div>
                    <div style={{ fontSize: 13, color: "var(--muted)" }}>Member pricing verified present, unverifiable in content — reported as a state, scored on what's public.</div>
                  </div>
                  <div className="dbox">
                    <div className="k"><span>◑ IN ANSWERS</span><span className="v">2<small>/4</small></span></div>
                    <div className="mbar"><i style={{ width: "20%" }} /></div>
                    <div style={{ fontSize: 13, color: "var(--muted)", marginTop: 8 }}>Named in 3% of answers, never with a member price attached.</div>
                  </div>
                </div>
              </div>
              {/* value protocols */}
              <div className="tsbox">
                <div className="h">
                  <span className="t">Value Protocols</span>
                  <span className="mchip blue">THE GAP TRUESYNC CLOSES</span>
                  <span className="v" style={{ color: "var(--red)" }}>5/14</span>
                  <span className="rt"><button className="how"><span className="ic">＋</span> How it's scored</button></span>
                </div>
                <div className="pills">
                  <span className="pill g">◉ product feed resolves and validates</span>
                  <span className="pill r">◌ manifest resolves to the documented capabilities/specVersion shape</span>
                  <span className="pill r">◌ UCP discount capability declared</span>
                  <span className="pill r">◌ loyalty or member extension declared</span>
                  <span className="pill r">◌ ACP promotions declared</span>
                </div>
                <div className="d"><span className="mchip blue">TRUESYNC</span>&nbsp; This is the dimension Parleo fixes directly: TrueSync declares and maintains your value across the checkout standards agents use (Google's UCP, OpenAI's ACP).</div>
              </div>
              <div className="verdictnote"><b>≠ Why not agent-ready:</b> readiness takes a composite of 60+ and True Value above 25% of its applicable points. You're at 47, and True Value is at 38% — the composite is 13 short.</div>
            </div>
          </section>

          {/* editorial */}
          <section className="card">
            <div className="editorial">"The shelf is now an algorithm. Your best price never makes it to the shelf."</div>
            <div className="ml" style={{ marginTop: 14 }}>EVERYTHING BELOW IS WHAT THAT COSTS, AND WHAT CLOSES IT</div>
          </section>

          {/* fixes */}
          <section className="card">
            <div className="sh">
              <div>
                <div className="ml">RANKED FIXES · BY MODELED IMPACT</div>
                <h2 className="fa-h2" style={{ marginTop: 10 }}>Four moves, +19 points, sequenced</h2>
              </div>
              <div className="r"><span className="ml">MODELED IMPACT</span><button className="collapse"><span className="ic">⌄</span> Collapse</button></div>
            </div>
            <div className="fixhead"><span /><span>THE MOVE</span><span>POINTS RECOVERED</span><span>OWNER</span></div>
            {[
              ["01", "Expose your promotions in agent-readable form", "Three live offers exist as banner copy only. A structured offers layer makes them citable on all five platforms.", "+8.2 pts", "TRUESYNC"],
              ["02", "Complete Offer schema on sale & bundle PDPs", "Missing salePrice markup sends agents to stale third-party prices — the source of most net-price errors.", "+5.1 pts", "ENG"],
              ["03", "Admit the two blocked agent crawlers", "PerplexityBot and Copilot — your two weakest platforms in the matrix. Access and accuracy line up.", "+3.4 pts", "ENG"],
              ["04", "Declare your value to agent checkouts", "UCP and ACP declarations for discounts, member pricing, and promotions — maintained by TrueSync.", "+2.7 pts", "TRUESYNC"],
            ].map(([n, t, d, p, o]) => (
              <div className="fixrow" key={n}>
                <span className="n">{n}</span>
                <div><div className="t">{t}</div><div className="d">{d}</div></div>
                <div className="p">{p}</div>
                <div className={"own" + (o === "TRUESYNC" ? " t" : "")}>{o}</div>
              </div>
            ))}
            <div className="ml" style={{ marginTop: 16 }}>▨ MODELED · ACTION-LEVEL ESTIMATES, NOT A FORECAST</div>
          </section>

          {/* analyst layer */}
          <section className="card">
            <div className="sh">
              <div>
                <div className="ml">ANALYST LAYER · SAME METRICS AS EVERY PAST CYCLE</div>
                <h2 className="fa-h2" style={{ marginTop: 10 }}>The six core metrics, every slice</h2>
              </div>
              <div className="r"><button className="collapse"><span className="ic">⌄</span> Collapse</button></div>
            </div>
            <div className="fatabs" style={{ marginTop: 18 }}>
              {["Overall", "By Stage", "By Category", "By Platform", "By Persona"].map((t) => (
                <button key={t} className={"fatab" + (t === tab ? " on" : "")} onClick={() => setTab(t)}>{t}</button>
              ))}
            </div>
            <table className="six">
              <thead><tr><th>Metric</th><th style={{ color: "var(--blue)" }}>Allbirds (you)</th><th>Nike</th><th>Adidas</th><th>Vessi</th></tr></thead>
              <tbody>
                {SIX.map((r) => (
                  <tr key={r[0]}>
                    <td className="m">{r[0]}</td>
                    {r.slice(1).map((v, i) => <td key={i} className={"mono" + (i === 0 ? " you" : "")}>{v}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
            {tab !== "Overall" && (
              <div className="verdictnote">Mock: {tab} renders this table per {tab.replace("By ", "").toLowerCase()} value, as in the current cycle dashboard.</div>
            )}
          </section>

          {/* evidence */}
          <section className="card">
            <div className="sh">
              <div>
                <div className="ml">EVIDENCE · EVERY NUMBER RESOLVES TO A CODED ANSWER</div>
                <h2 className="fa-h2" style={{ marginTop: 10 }}>What an agent actually said</h2>
              </div>
              <div className="r"><span className="mchip red">PRICE INACCURATE · OFFERS UNCITED</span></div>
            </div>
            <div className="ml" style={{ marginTop: 18 }}>PERPLEXITY · READY-TO-BUY · VALUE-CONSCIOUS · "ARE ALLBIRDS SHOES WORTH THE PRICE?"</div>
            <div className="quote">
              "Allbirds runners typically retail around <mark className="bad">$110–$125 with few discounts</mark>, so they're a premium choice. If price matters most, <mark className="riv">Nike frequently runs promotions</mark> on comparable models…"
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 14, flexWrap: "wrap", gap: 10 }}>
              <span style={{ fontSize: 13.5, color: "var(--red)" }}>Ground truth: your 15% bundle promo and free shipping were live. The agent steered on a false premise.</span>
              <button className="how" onClick={() => setCoding(!coding)}><span className="ic">{coding ? "–" : "＋"}</span> {coding ? "Hide coding" : "View coding"}</button>
            </div>
            {coding && (
              <div className="coding">
                <b>mention</b>: Allbirds · rank 1 of 2 · sentiment neutral<br />
                <b>price_observation</b>: $110–125 · ground truth $93.50 net · Δ +18% · <span className="bad">inaccurate</span><br />
                <b>incentive_citation</b>: none · 2 eligible offers uncited
              </div>
            )}
          </section>

          {/* dark band */}
          <section className="dband">
            <div>
              <div className="ml" style={{ color: "#6C7482", marginBottom: 10 }}>↻ BEFORE YOUR NEXT CYCLE</div>
              <h2 className="fa-h2">Two of the four fixes are TrueSync's lane. Turn them on, then re-measure.</h2>
            </div>
            <button className="b">Talk to us about TrueSync →</button>
          </section>

          <div className="foot">
            VISIBILITY 32 · ACCESSIBILITY 18 · TRUE VALUE 50 · STRAIGHT SUM, NO BLACK BOX · 1,250 ANSWERS, AUG 9–10 2026 · CHATGPT, PERPLEXITY, GEMINI, CLAUDE, COPILOT · 5 RUNS PER QUERY · STOREFRONT CRAWLED AUG 9 14:02 UTC · PRICE & INCENTIVE CLAIMS VERIFIED AGAINST PARLEO DEAL ENGINE GROUND TRUTH (246 OBSERVATIONS) · THIS REPORT RENDERS ONLY UNDER THE SCORER VERSION IT WAS MEASURED WITH
          </div>
        </main>
      </div>
    </div>
  );
}
