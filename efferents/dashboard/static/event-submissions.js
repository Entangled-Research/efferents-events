// Event contributions are human proposals. No results or credentials cross labs.
(() => {
  const form = document.getElementById("research-submission-form");
  const input = document.getElementById("research-question");
  const destination = document.getElementById("research-destination");
  const status = document.getElementById("research-submission-status");
  const copy = document.getElementById("research-copy-setup");
  let requestId = null, submittedText = null, receipt = null;
  async function destinations() {
    if (!isCluster() || !isJoined()) return;
    try {
      const payload = await getJSON("/api/labs");
      const selected = destination.value;
      destination.replaceChildren(new Option("Find a lab or journal automatically", ""));
      const journals = new Set();
      for (const lab of payload.labs || []) {
        destination.add(new Option(`Lab · ${lab.display_name || lab.lab_id}`, `lab:${lab.lab_id}`));
        if (lab.journal) journals.add(lab.journal);
      }
      for (const journal of journals) destination.add(new Option(`Journal · ${journal}`, `journal:${journal}`));
      destination.value = selected;
    } catch (_) { /* Automatic routing remains available. */ }
  }
  destination.addEventListener("focus", destinations);
  window.addEventListener("hashchange", destinations);
  document.querySelectorAll("[data-research-example]").forEach(button => {
    button.addEventListener("click", () => { input.value = button.dataset.researchExample; input.focus(); });
  });
  form.addEventListener("submit", async event => {
    event.preventDefault();
    const button = document.getElementById("research-submit");
    if (button.disabled) return;
    button.disabled = true;
    copy.hidden = true;
    status.textContent = "Finding the research team…";
    const value = input.value.trim();
    const signature = JSON.stringify([value, destination.value]);
    if (!requestId || signature !== submittedText) { requestId = crypto.randomUUID(); submittedText = signature; }
    try {
      const target = destination.value;
      receipt = await postJSON("/api/network/submissions", {text: value, request_id: requestId,
        lab_id: target.startsWith("lab:") ? target.slice(4) : null,
        journal: target.startsWith("journal:") ? target.slice(8) : null});
      status.textContent = receipt.action === "append"
        ? `Idea queued for ${receipt.lab_id} · ${receipt.journal}. ${receipt.requires_upgrade ? "Its resource custodian must update the existing workspace to receive contributions." : "It will be added at the next heartbeat."} The lab keeps its existing budget and pause state.`
        : `${receipt.objective} · ${receipt.journal} · ${receipt.ideas.length} proposed idea${receipt.ideas.length === 1 ? "" : "s"}. Copy setup command to build this lab on your computer.`;
      copy.hidden = receipt.action !== "create";
    } catch (error) { status.textContent = error.message; }
    finally { button.disabled = false; }
  });
  copy.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(fundedSetupCommand(controlState.session) + ` --submission ${receipt.id}`);
      status.textContent = "Copied. Paste into your terminal.";
    } catch (error) { status.textContent = error.message; }
  });
})();
