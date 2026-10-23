const isDevelopment = import.meta.env.DEV;

export function logInfo(message, metadata = {}) {
  if (!isDevelopment) {
    return;
  }

  console.info(`[LocalRAG] ${message}`, metadata);
}

export function logError(message, metadata = {}) {
  if (!isDevelopment) {
    return;
  }

  console.error(`[LocalRAG] ${message}`, metadata);
}