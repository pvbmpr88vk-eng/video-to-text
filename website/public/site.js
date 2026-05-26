(function () {
  var el = document.getElementById("gpu-status");
  if (!el) return;

  function label(data) {
    if (!data.configured) return { text: "GPU: не настроен", cls: "gpu-status--off" };
    if (data.ready) return { text: "GPU CUDA: онлайн", cls: "gpu-status--on" };
    if (data.api_ok && data.nodes_online === 0) {
      return { text: "GPU: узел offline", cls: "gpu-status--warn" };
    }
    return { text: "GPU: недоступен", cls: "gpu-status--warn" };
  }

  function render(data) {
    var s = label(data);
    el.textContent = s.text;
    el.className = "gpu-status " + s.cls;
    var detail = document.getElementById("gpu-detail");
    if (!detail) return;
    if (data.ready && data.runtimes && data.runtimes.length) {
      var rt = data.runtimes.map(function (r) { return r.id; }).join(", ");
      detail.textContent = "Runtime: " + rt + " · узлов: " + data.nodes_online;
    } else if (data.error) {
      detail.textContent = data.error;
    } else {
      detail.textContent = "";
    }
  }

  fetch("/api/gpu-status", { cache: "no-store" })
    .then(function (r) { return r.json(); })
    .then(render)
    .catch(function () {
      el.textContent = "GPU: статус недоступен";
      el.className = "gpu-status gpu-status--warn";
    });
})();
