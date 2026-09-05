// Voice edits the draft only. Submission stays with the existing goal form.
(() => {
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  const button = document.querySelector("#voice-goal");
  const input = document.querySelector("#agent-input");
  const status = document.querySelector("#voice-status");
  if (!Recognition || !button || !input) return;

  let active = null;
  const reset = (message = "") => {
    const previous = active;
    active = null; // Ignore callbacks from cancelled or completed sessions.
    button.classList.remove("listening");
    button.setAttribute("aria-pressed", "false");
    button.setAttribute("aria-label", "Speak a shopping goal");
    status.textContent = message;
    if (previous) {
      try { previous.abort(); } catch { /* Already disconnected. */ }
    }
  };

  button.hidden = false;
  document.querySelector("#goal-search-icon").hidden = true;
  button.addEventListener("click", () => {
    if (active) { reset("Voice input stopped. You can keep typing."); return; }
    if (input.disabled) return;
    try {
      const recognition = new Recognition();
      active = recognition;
      recognition.lang = "en-IN";
      recognition.continuous = false;
      recognition.interimResults = false;
      recognition.maxAlternatives = 1;
      recognition.onstart = () => {
        if (active !== recognition) return;
        status.textContent = "Listening. Speak your goal, then review before dispatching.";
      };
      recognition.onresult = event => {
        if (active !== recognition || input.disabled) return;
        const transcript = Array.from(event.results)
          .filter(result => result.isFinal)
          .map(result => result[0]?.transcript || "").join(" ").trim();
        if (!transcript) return;
        input.value = transcript;
        reset("Goal transcribed. Review or edit it, then press Dispatch BOUND.");
        input.focus();
      };
      recognition.onerror = event => {
        if (active !== recognition) return;
        const messages = {
          "not-allowed": "Microphone permission is required for voice input.",
          "service-not-allowed": "Microphone permission is required for voice input.",
          "audio-capture": "No microphone is available. You can type your goal.",
          "no-speech": "No speech detected. Try again or type your goal.",
          "network": "Voice input could not connect. Try again or type your goal."
        };
        reset(messages[event.error] || "Voice input is unavailable. You can type your goal.");
      };
      recognition.onend = () => {
        if (active === recognition) reset("No speech detected. Try again or type your goal.");
      };
      button.classList.add("listening");
      button.setAttribute("aria-pressed", "true");
      button.setAttribute("aria-label", "Stop voice input");
      status.textContent = "Starting microphone...";
      recognition.start();
    } catch {
      reset("Voice input is unavailable. You can type your goal.");
    }
  });
  // Typing or submitting takes precedence over late recognition results.
  input.addEventListener("input", () => { if (active) reset(); });
  document.querySelector("#agent-form").addEventListener("submit", () => reset(), true);
  new MutationObserver(() => {
    button.disabled = input.disabled;
    if (input.disabled) reset();
  }).observe(input, { attributes: true, attributeFilter: ["disabled"] });
  window.addEventListener("pagehide", () => reset());
})();
