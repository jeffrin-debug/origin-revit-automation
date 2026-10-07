// demo.js - stand-in for origin_web.py so the page can be clicked through with no Revit.
//
// Loaded by index.html, but only USED when the page is opened from GitHub Pages (*.github.io)
// or with ?demo in the URL. Sample layouts only - no client data. Nothing runs anywhere: the
// "run" is a timer that walks the same states the real bridge reports.

(function(){
  const W = "C:\\ORIGIN\\work";
  const now = () => new Date().toISOString().slice(0,16).replace("T"," ");
  const folders = ["C:\\ORIGIN\\layouts\\Client A", "C:\\ORIGIN\\layouts\\Client B"];
  const files = {
    [folders[0]]: [
      ["Office_L1.rvt", 7.6, "2026-09-21 13:29"], ["Office_L2.rvt", 6.9, "2026-09-22 10:02"],
      ["Clinic_Wing_B.rvt", 11.9, "2026-09-30 16:48"], ["Lab_01.rvt", 6.1, "2026-08-04 16:05"],
      ["Tower_Full_Model.rvt", 486.2, "2026-07-06 16:23"]],
    [folders[1]]: [
      ["Warehouse_Mezz.rvt", 9.1, "2026-08-11 13:35"], ["Retail_Unit_3.rvt", 6.5, "2026-07-16 14:54"]],
    "C:\\ORIGIN\\layouts\\Client C": [["School_Block_C.rvt", 8.2, "2026-10-01 09:12"]],
  };
  const ledger = {
    "Office_L2.rvt": {ceiling:"ok", panels:"ok", review:"pending", status:"ok", updated:"2026-10-06 18:02"},
    "Lab_01.rvt": {ceiling:"ok", panels:"ok", review:"approved", promoted:"yes", status:"ok", updated:"2026-10-02 11:40"},
    "Retail_Unit_3.rvt": {ceiling:"ok", panels:"-", review:"-", status:"ok", updated:"2026-10-05 15:10"},
  };
  const out = { panels:["Office_L2.rvt"], ceiling:["Retail_Unit_3.rvt"], sim:["Lab_01.rvt"] };
  const reports = {
    "Office_L2.rvt": {counts:{walls:42, ceilings:9, soffits:2, columns:3, beams:0},
      flags:["CEILING GAPS: 1 patch(es), 0 unboarded"],
      warnings:{walls:["W017 face B: joint off-stud at 96 in (no stud in reach)", "W023: no stud qualifies for an outlet"],
                columns:["K002: angled 3.0 deg - skipped"]}},
    "Lab_01.rvt": {counts:{walls:18, ceilings:4, soffits:0, columns:0, beams:2}, flags:[], warnings:{}},
  };
  function reportFor(n){
    if(reports[n]) return reports[n];
    let h = 0; for(const c of n) h = (h * 31 + c.charCodeAt(0)) % 997;
    return {counts:{walls:12 + h % 40, ceilings:3 + h % 9, soffits:h % 3, columns:h % 4, beams:h % 2},
            flags: h % 3 === 0 ? ["CEILING JOINTS OFF FRAMING: 1"] : [],
            warnings: h % 2 ? {walls:["W00" + (h % 9) + ": end piece 14 in could not reach 16 in (jamb within 4 in)"]} : {}};
  }
  let job = {state:"idle"}, timer = null;

  function stateFor(){
    const j = Object.assign({}, job);
    if(j.state === "running" && j.kind === "open") j.elapsed = Math.floor((Date.now() - j.t0) / 1000);
    if(j.state === "running" && j.kind !== "open"){
      const t = (Date.now() - j.t0) / 1000, per = j.stages.includes("panels") ? 9 : 4;
      const i = Math.min(Math.floor(t / per), j.files.length - 1);
      const into = t - i * per;
      j.elapsed = Math.floor(t);
      j.progress = {index:i + 1, total:j.files.length, file:j.names[i],
        stage: into < 1.5 ? "opening" : (j.stages.includes("ceiling") && into < 4) ? "ceilings" : "panels",
        done: j.names.slice(0, i).map(n => ({file:n, status: n.startsWith("Warehouse") && j.stages.includes("ceiling") ? "ceiling failed - rolled back, not saved" : "ok"}))};
    }
    return {bridge:{alive:true, busy: job.state === "running", doc:"Office_L1", status:"idle", dir:W + "\\bridge",
                    text: job.state === "running" ? "busy running the job" : "connected - Revit doc 'Office_L1' (demo)"},
            job:j, folders, work:W, dirs:{},
            setup:{revit_installed:true, revit_running:true, dynamo_trusted:true, host_exists:true,
                   revit_exe:"C:\\Program Files\\Autodesk\\Revit 2026\\Revit.exe", dyn:W + "\\dynamo\\ORIGIN Pipeline Bridge.dyn",
                   work:"C:\\Users\\you\\Documents\\ORIGIN"}};
  }

  function finish(){
    const rows = job.names.map(n => {
      const fail = n.startsWith("Warehouse") && job.stages.includes("ceiling");
      const st = (job.entries.find(e => e.path.endsWith(n)) || {}).steps || [];
      const r = {file:n, steps:st, sec: job.stages.includes("panels") ? 41 + n.length : 3.2,
        ceiling: job.stages.includes("ceiling") ? (fail ? "failed verification" : "ok") : null,
        panels: !fail && job.stages.includes("panels") ? "ok" : null,
        status: fail ? "ceiling failed - rolled back, not saved" : "ok"};
      if(fail) r.fail_reasons = ["rooms found cover 41% of the blanket ceiling (< 60%) - rooms were missed"];
      const e = ledger[n] || (ledger[n] = {ceiling:"-", panels:"-", review:"-"});
      if(r.ceiling) e.ceiling = r.ceiling;
      if(r.panels){ e.panels = "ok"; e.review = "pending"; if(!out.panels.includes(n)) out.panels.push(n);
                    out.ceiling = out.ceiling.filter(x => x !== n); }
      else if(r.ceiling === "ok" && !out.ceiling.includes(n)) out.ceiling.push(n);
      e.status = r.status; e.updated = now();
      return r;
    });
    const ok = rows.filter(r => r.status === "ok").length;
    job = {state:"done", result:{requested:rows.length, files:rows, totals:{ok},
           dialogs_auto_answered:[]}};
  }

  window.DemoAPI = async function(path, body){
    await new Promise(r => setTimeout(r, 120));
    const fail = m => { throw new Error(m); };
    if(path === "/api/state") return stateFor();
    if(path === "/api/layouts") return folders.map(f => ({folder:f, exists:true, files:(files[f] || []).map(([name, mb, mod]) => {
      const e = ledger[name] || {};
      return {name, path:f + "\\" + name, mb, modified:mod, too_big: mb > 50,
              ceiling:e.ceiling || "-", panels:e.panels || "-", review:e.review || "-"};
    })}));
    if(path === "/api/outputs") return ["panels","ceiling","sim"].flatMap(st => out[st].map(n => ({
      name:n, stage:st, path:W + "\\" + n, review:(ledger[n] || {}).review || "-", status:(ledger[n] || {}).status,
      updated:(ledger[n] || {}).updated, summary: st === "ceiling" ? null : reportFor(n)})));
    if(path === "/api/run"){
      if(job.state === "running") fail("a run is already in progress");
      const entries = (body.files || []).map(f => typeof f === "string" ? {path:f, steps:["ceiling","walls","ceilings","soffits","columns","beams"]} : f)
                                        .filter(f => f.steps && f.steps.length);
      if(!entries.length) fail("no layout files selected (or nothing ticked to run on them)");
      const all = entries.flatMap(e => e.steps);
      const stages = [all.includes("ceiling") && "ceiling", all.some(x => x !== "ceiling") && "panels"].filter(Boolean);
      body = {files: entries.map(e => e.path)};
      job = {state:"running", kind:"batch", t0:Date.now(), files:body.files, stages, entries,
             names: body.files.map(p => p.split("\\").pop())};
      clearTimeout(timer);
      timer = setTimeout(finish, (stages.includes("panels") ? 9 : 4) * body.files.length * 1000);
      return job;
    }
    if(path === "/api/run-open"){
      if(job.state === "running") fail("a run is already in progress");
      const steps = body.steps || [];
      if(!steps.length) fail("tick at least one step");
      job = {state:"running", kind:"open", t0:Date.now(), steps, doc:"Office_L1"};
      clearTimeout(timer);
      timer = setTimeout(() => {
        const gens = {};
        steps.filter(x => x !== "ceiling").forEach((g, i) => gens[g] = {boards_created: [64, 12, 4, 9, 6][i % 5], warnings: g === "walls" ? ["W004: end piece 14 in kept (jamb within 4 in)"] : []});
        job = {state:"done", kind:"open", result:{doc:"Office_L1", ok:true,
          ceiling: steps.includes("ceiling") ? {ok:true} : undefined,
          panels: Object.keys(gens).length ? {ok:true, generators:gens} : undefined}};
      }, 5000);
      return job;
    }
    if(path === "/api/dismiss"){ if(job.state !== "running") job = {state:"idle"}; return stateFor().job; }
    if(path === "/api/folders"){
      if(body.action === "pick"){
        const f = "C:\\ORIGIN\\layouts\\Client C";
        if(folders.includes(f)) return {folders, cancelled:true};
        folders.push(f); return {folders};
      }
      if(body.action === "remove"){ const i = folders.indexOf(body.path); if(i >= 0) folders.splice(i, 1); }
      return {folders};
    }
    if(path === "/api/review"){
      if(!out.panels.includes(body.name)) fail(body.name + " is not in 02_panels_done");
      (ledger[body.name] = ledger[body.name] || {}).review = body.decision; ledger[body.name].updated = now();
      return ledger[body.name];
    }
    if(path === "/api/promote"){
      const moved = out.panels.filter(n => (ledger[n] || {}).review === "approved");
      moved.forEach(n => { out.panels = out.panels.filter(x => x !== n); out.sim.push(n); ledger[n].promoted = "yes"; });
      return {moved, missing:[]};
    }
    if(path === "/api/open") fail("Demo: on a real PC this opens the folder or model on that computer.");
    fail("not found");
  };
})();
