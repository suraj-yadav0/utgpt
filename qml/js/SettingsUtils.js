.pragma library

// Shared pure logic for SettingsPage.qml.
// UI-free so it can run under qmltestrunner (QtTest).

function snapTemperature(value) {
    return Math.round(value * 10) / 10;
}

function snapMaxTokens(value) {
    if (value <= 200) {
        return Math.round(value / 10) * 10;
    } else if (value <= 1000) {
        return Math.round(value / 50) * 50;
    } else if (value <= 10000) {
        return Math.round(value / 500) * 500;
    }
    return Math.round(value / 5000) * 5000;
}

function fallbackModelInfo(filename) {
    var fn = filename.toLowerCase();
    if (fn.indexOf("smollm2") >= 0) {
        return {
            name: "SmolLM2-1.7B",
            developer: "Hugging Face",
            size: "~1.0 GB",
            context: "8,192 tokens",
            maxContext: 8192,
            quant: "Q4_K_M (4-bit)",
            usage: "Fast general chat, low resource devices"
        };
    } else if (fn.indexOf("qwen") >= 0) {
        return {
            name: "Qwen2.5-1.5B",
            developer: "Alibaba Group",
            size: "~1.0 GB",
            context: "32,768 tokens",
            maxContext: 32768,
            quant: "Q4_K_M (4-bit)",
            usage: "Excellent multilingual capabilities, coding & reasoning"
        };
    } else if (fn.indexOf("llama-3.2-1b") >= 0) {
        return {
            name: "Llama-3.2-1B",
            developer: "Meta",
            size: "~800 MB",
            context: "128,000 tokens",
            maxContext: 128000,
            quant: "Q4_K_M (4-bit)",
            usage: "Ultra-fast assistant, agentic tasks, long contexts"
        };
    } else if (fn.indexOf("llama-3.2-3b") >= 0) {
        return {
            name: "Llama-3.2-3B",
            developer: "Meta",
            size: "~2.0 GB",
            context: "128,000 tokens",
            maxContext: 128000,
            quant: "Q4_K_M (4-bit)",
            usage: "Smart general assistant, high quality logic & reasoning"
        };
    } else if (fn.indexOf("gemma") >= 0) {
        return {
            name: "Gemma-2-2B",
            developer: "Google",
            size: "~1.7 GB",
            context: "8,192 tokens",
            maxContext: 8192,
            quant: "Q4_K_M (4-bit)",
            usage: "Lightweight high-quality chatting, instruction following"
        };
    } else if (fn.indexOf("phi-3") >= 0) {
        return {
            name: "Phi-3-mini-4K",
            developer: "Microsoft",
            size: "~2.2 GB",
            context: "4,096 tokens",
            maxContext: 4096,
            quant: "Q4_K_M (4-bit)",
            usage: "Reasoning, logical tasks, math and coding"
        };
    } else if (fn.indexOf("tinyllama") >= 0) {
        return {
            name: "TinyLlama-1.1B",
            developer: "TinyLlama Project",
            size: "~700 MB",
            context: "2,048 tokens",
            maxContext: 2048,
            quant: "Q4_K_M (4-bit)",
            usage: "Extremely fast, simple chats on low-spec hardware"
        };
    }
    return {
        name: filename,
        developer: "Unknown",
        size: "Unknown",
        context: "Unknown",
        maxContext: 2048,
        quant: "GGUF",
        usage: "General inference"
    };
}

// catalog: array of {filename, ...}. Case-insensitive exact match first,
// legacy filename fallback second.
function getModelInfo(catalog, filename) {
    if (!filename) {
        return null;
    }
    var fn = filename.toLowerCase();
    if (catalog) {
        for (var i = 0; i < catalog.length; i++) {
            var item = catalog[i];
            if (item.filename && item.filename.toLowerCase() === fn) {
                return item;
            }
        }
    }
    return fallbackModelInfo(filename);
}

function maxTokensForModel(catalog, filename, currentMax, defaultLimit) {
    var info = getModelInfo(catalog, filename);
    var limit = info ? info.maxContext : (defaultLimit || 2048);
    if (currentMax > limit) {
        return limit;
    }
    return currentMax;
}
