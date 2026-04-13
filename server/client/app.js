const state = {
  appSessionId: crypto.randomUUID(),
  imageSessionId: crypto.randomUUID(),
  conversationId: crypto.randomUUID(),
  turnIndex: 0,
  graphPath: "",
  sessionRoot: "",
}

const form = document.querySelector("#composer")
const formError = document.querySelector("#formError")
const submitButton = document.querySelector("#submitButton")
const imagePathInput = document.querySelector("#imagePath")
const sessionRootInput = document.querySelector("#sessionRoot")
const graphPathInput = document.querySelector("#graphPath")
const promptInput = document.querySelector("#prompt")
const previewWidthInput = document.querySelector("#previewWidth")
const previewHeightInput = document.querySelector("#previewHeight")
const messages = document.querySelector("#messages")
const previewImage = document.querySelector("#previewImage")
const previewEmpty = document.querySelector("#previewEmpty")
const surfaces = document.querySelector("#surfaces")
const workflowGraphPath = document.querySelector("#workflowGraphPath")
const workflowExports = document.querySelector("#workflowExports")
const statusText = document.querySelector("#statusText")
const conversationId = document.querySelector("#conversationId")

conversationId.textContent = state.conversationId

function addMessage(role, text) {
  const wrapper = document.createElement("div")
  wrapper.className = role === "user"
    ? "ml-auto max-w-3xl rounded-2xl bg-amber-400 px-4 py-3 text-sm text-stone-950"
    : "max-w-3xl rounded-2xl border border-stone-800 bg-stone-950/70 px-4 py-3 text-sm text-stone-100"
  wrapper.textContent = text
  messages.appendChild(wrapper)
  messages.scrollTop = messages.scrollHeight
}

function renderPreview(preview) {
  if (!preview?.base64Data || !preview?.mimeType) {
    previewImage.classList.add("hidden")
    previewEmpty.classList.remove("hidden")
    return
  }
  previewImage.src = `data:${preview.mimeType};base64,${preview.base64Data}`
  previewImage.classList.remove("hidden")
  previewEmpty.classList.add("hidden")
}

function renderSurfaces(items) {
  surfaces.innerHTML = ""
  if (!items?.length) {
    surfaces.textContent = "No adjustment surfaces available yet."
    return
  }
  for (const item of items) {
    const card = document.createElement("article")
    card.className = "mb-3 rounded-xl border border-stone-800 bg-stone-950/60 p-3"

    const title = document.createElement("div")
    title.className = "flex items-start justify-between gap-3"
    title.innerHTML = `
      <div>
        <p class="font-medium text-stone-100">${item.module}</p>
        <p class="text-xs uppercase text-stone-500">${item.stage}</p>
      </div>
      <span class="rounded-full px-2 py-1 text-xs ${item.present ? "bg-emerald-950 text-emerald-300" : "bg-stone-800 text-stone-400"}">${item.present ? "present" : "addable"}</span>
    `

    const summary = document.createElement("p")
    summary.className = "mt-2 text-sm text-stone-300 text-pretty"
    summary.textContent = item.summary

    const params = document.createElement("p")
    params.className = "mt-2 font-mono text-xs text-stone-500"
    params.textContent = item.params?.length ? item.params.join(", ") : "no direct params"

    card.append(title, summary, params)
    surfaces.appendChild(card)
  }
}

function renderExports(items) {
  workflowExports.innerHTML = ""
  if (!items?.length) {
    workflowExports.textContent = "No exports yet."
    return
  }
  for (const item of items) {
    const row = document.createElement("div")
    row.className = "rounded-xl border border-stone-800 bg-stone-950/60 px-3 py-2"
    row.innerHTML = `
      <p class="font-medium text-stone-200">${item.format}</p>
      <p class="break-all font-mono text-xs text-stone-500">${item.path}</p>
    `
    workflowExports.appendChild(row)
  }
}

function setPending(isPending) {
  submitButton.disabled = isPending
  submitButton.textContent = isPending ? "Running..." : "Run agent turn"
  statusText.textContent = isPending
    ? "Agent is iterating on the current graph."
    : statusText.textContent
}

function nextTurnId() {
  state.turnIndex += 1
  return `turn-${String(state.turnIndex).padStart(4, "0")}`
}

function showError(message) {
  formError.textContent = message
  formError.classList.remove("hidden")
}

function clearError() {
  formError.textContent = ""
  formError.classList.add("hidden")
}

form.addEventListener("submit", async (event) => {
  event.preventDefault()
  clearError()

  const imagePath = imagePathInput.value.trim()
  const prompt = promptInput.value.trim()
  if (!imagePath || !prompt) {
    showError("Image path and prompt are required.")
    return
  }

  state.sessionRoot = sessionRootInput.value.trim()
  state.graphPath = graphPathInput.value.trim() || state.graphPath

  addMessage("user", prompt)
  setPending(true)

  try {
    const response = await fetch("/v1/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        schemaVersion: "1.0",
        requestId: crypto.randomUUID(),
        session: {
          appSessionId: state.appSessionId,
          imageSessionId: state.imageSessionId,
          conversationId: state.conversationId,
          turnId: nextTurnId(),
        },
        message: { role: "user", text: prompt },
        workspace: {
          imagePath,
          graphPath: state.graphPath || undefined,
          sessionRoot: state.sessionRoot || undefined,
          previewWidth: Number.parseInt(previewWidthInput.value, 10),
          previewHeight: Number.parseInt(previewHeightInput.value, 10),
        },
        fast: false,
        refinement: {
          mode: "multi-turn",
          enabled: true,
          maxPasses: 8,
          passIndex: 1,
          goalText: prompt,
        },
      }),
    })

    const payload = await response.json()
    if (!response.ok || payload.status === "error") {
      throw new Error(payload.error?.message || "Request failed")
    }

    const workflow = payload.workflow
    state.graphPath = workflow.graphPath || state.graphPath
    graphPathInput.value = state.graphPath
    workflowGraphPath.textContent = workflow.graphPath || ""
    renderPreview(workflow.preview)
    renderSurfaces(workflow.adjustmentSurfaces)
    renderExports(workflow.exports)
    statusText.textContent = payload.assistantMessage.text
    addMessage("assistant", payload.assistantMessage.text)
    promptInput.value = ""
  } catch (error) {
    showError(error instanceof Error ? error.message : "Unexpected error")
  } finally {
    setPending(false)
  }
})
