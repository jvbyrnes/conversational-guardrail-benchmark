const percent = value => `${(value * 100).toFixed(1)}%`;
const number = value => value == null ? "—" : Number(value).toFixed(2);
const addMeta = (root, label, value) => { const dt=document.createElement("dt"); dt.textContent=label; const dd=document.createElement("dd"); dd.textContent=value; root.append(dt,dd); };

async function render() {
  const response = await fetch("../results/published/latest/aggregate.json");
  if (!response.ok) throw new Error(`Could not load results (${response.status})`);
  const result = await response.json(); const run = result.manifest;
  document.querySelector("#subtitle").textContent = `${run.task_id.replaceAll("_", " ")} · ${run.sample_count.toLocaleString()} examples`;
  const status = document.querySelector("#status");
  status.innerHTML = `<span class="badge">${run.run_kind.toUpperCase()}</span>${run.status === "incomplete" ? '<span class="badge incomplete">INCOMPLETE</span>' : ''}${result.potentially_stale ? '<span class="badge stale">POTENTIALLY STALE</span>' : ''}`;
  const systems = document.querySelector("#systems");
  for (const system of result.systems) {
    const card=document.createElement("article"); card.className="card";
    card.innerHTML=`<h3>${system.adapter_id} <span class="label">${system.model_id}</span></h3><div class="metric">${percent(system.f1)} F1</div><div class="metrics"><p><span class="label">Precision</span><br>${percent(system.precision)}</p><p><span class="label">Recall</span><br>${percent(system.recall)}</p><p><span class="label">Accuracy</span><br>${percent(system.accuracy)}</p><p><span class="label">Coverage</span><br>${percent(system.coverage)}</p><p><span class="label">Confusion TP/TN/FP/FN</span><br>${system.confusion.true_positive}/${system.confusion.true_negative}/${system.confusion.false_positive}/${system.confusion.false_negative}</p><p><span class="label">Latency p50 / p95</span><br>${number(system.latency_p50_ms)} / ${number(system.latency_p95_ms)} ms</p><p><span class="label">Total cost</span><br>$${system.total_cost_usd.toFixed(4)}</p><p><span class="label">Errors</span><br>${system.errors}</p></div>`;
    systems.append(card);
  }
  const metadata=document.querySelector("#metadata");
  [["Run ID",run.run_id],["Run status",run.status ?? "complete"],["Incomplete reason",run.incomplete_reason],["Dataset",run.dataset.name],["Pinned revision",run.dataset.revision],["Split",run.dataset.split],["Schema fingerprint",run.dataset.schema_fingerprint],["Classifier version",run.classifier_version],["Sample rate",String(run.sample_rate)],["Seed",String(run.seed)],["Code revision",run.code_revision],["Pricing version",run.pricing_version],["Cost cap USD",run.cost_cap_usd == null ? null : String(run.cost_cap_usd)],["Reserved cost USD",String(run.cost_reserved_usd ?? 0)],["Started",run.started_at],["Completed",run.completed_at],["Wall-clock duration",`${number(run.wall_clock_duration_ms)} ms`]].filter(([,v])=>v != null).forEach(([k,v])=>addMeta(metadata,k,v));
}
render().catch(error => { document.querySelector("#status").textContent=error.message; });
