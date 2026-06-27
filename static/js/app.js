if ("serviceWorker" in navigator) {
    window.addEventListener("load", function () {
        navigator.serviceWorker.register("/static/service-worker.js").catch(function () {
            // 学習用アプリなので、Service Worker登録に失敗しても通常利用はできます。
        });
    });
}

let englishVoice = null;

function loadVoices() {
    if (!("speechSynthesis" in window)) {
        return;
    }

    const voices = window.speechSynthesis.getVoices();

    // 日本語音声を拾ってカタカナっぽく読む事故を避けるため、英語音声を優先します。
    englishVoice =
        voices.find(v => v.lang === "en-US" && /Samantha|Alex|Google|Microsoft|Jenny|Aria|Guy|Daniel|Karen/i.test(v.name)) ||
        voices.find(v => v.lang === "en-GB" && /Daniel|Google|Microsoft|George|Libby|Ryan/i.test(v.name)) ||
        voices.find(v => v.lang === "en-US") ||
        voices.find(v => v.lang === "en-GB") ||
        voices.find(v => v.lang && v.lang.toLowerCase().startsWith("en")) ||
        null;
}

if ("speechSynthesis" in window) {
    loadVoices();
    window.speechSynthesis.onvoiceschanged = loadVoices;
}

function naturalizeEnglishForTTS(text) {
    let t = (text || "").trim();

    // 英語音声が「a」を文字名の "A / エー" と読む事故を減らす。
    // 画面表示は変えず、音声入力だけを少し自然な形へ寄せます。
    if (/^a$/i.test(t)) {
        return "uh";
    }

    // "This is a" のように a で終わる不完全な句は、文字名扱いされやすいので弱形に寄せる。
    t = t.replace(/\b([Tt]his is) a$/g, "$1 uh");
    t = t.replace(/\b([Tt]hat is) a$/g, "$1 uh");
    t = t.replace(/\b([Ii]t is) a$/g, "$1 uh");

    // a + 子音始まりの単語は弱く読ませる。例: a pen -> uh pen
    t = t.replace(/\ba\s+([bcdfghjklmnpqrstvwxyz][a-z]*)\b/gi, "uh $1");

    // an は雑に "ann" へ寄せると読み上げが安定する端末がある。
    t = t.replace(/\ban\s+([aeiou][a-z]*)\b/gi, "ann $1");

    // 短い句はピリオドを足すと読み上げが安定しやすい。
    if (!/[.!?]$/.test(t)) {
        t = t + ".";
    }

    return t;
}

function speakEnglish(text, rate) {
    if (!text || !("speechSynthesis" in window)) {
        alert("このブラウザでは音声読み上げが使えません。");
        return;
    }

    window.speechSynthesis.cancel();

    const utterance = new SpeechSynthesisUtterance(naturalizeEnglishForTTS(text));
    utterance.lang = "en-US";
    utterance.rate = rate || 0.9;
    utterance.pitch = 1.0;
    utterance.volume = 1.0;

    if (englishVoice) {
        utterance.voice = englishVoice;
    }

    window.speechSynthesis.speak(utterance);
}

document.querySelectorAll("[data-speak]").forEach(function (button) {
    button.addEventListener("click", function () {
        const text = button.getAttribute("data-speak");
        const rate = parseFloat(button.getAttribute("data-rate") || "0.9");
        speakEnglish(text, rate);
    });
});


document.querySelectorAll(".copy-button").forEach(function (button) {
    button.addEventListener("click", async function () {
        const targetId = button.getAttribute("data-copy-target");
        const target = document.getElementById(targetId);
        if (!target) return;
        try {
            await navigator.clipboard.writeText(target.value || target.textContent || "");
            const oldText = button.textContent;
            button.textContent = "コピーしました";
            setTimeout(function () { button.textContent = oldText; }, 1200);
        } catch (e) {
            target.select();
            document.execCommand("copy");
        }
    });
});
