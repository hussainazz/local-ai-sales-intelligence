# Primary references

The implementation was checked against these primary references on 2026-11-03. Runtime validation results are documented separately.

- [n8n Webhook](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.webhook/) describes webhook methods, authentication and test/production registration.
- [n8n HTTP Request](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.httprequest/) describes JSON requests and header credentials.
- [n8n Respond to Webhook](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.respondtowebhook/) describes the response-node mode used by the two webhook workflows.
- [LangGraph Graph API](https://docs.langchain.com/oss/python/langgraph/graph-api) documents shared state, graph nodes and edges.
- [LangChain ChatOllama](https://docs.langchain.com/oss/python/integrations/chat/ollama) documents the local integration package and structured-output support.
- [Ollama embeddings API](https://docs.ollama.com/api/embed) documents local batch embeddings.
- [Ollama local-only configuration](https://docs.ollama.com/faq#how-do-i-disable-ollamas-cloud-features) documents `OLLAMA_NO_CLOUD=1` on the Ollama server.
- [n8n release 2.46.4](https://github.com/n8n-io/n8n/releases/tag/n8n%402.46.4) and [Ollama release 0.40.14](https://github.com/ollama/ollama/releases/tag/v0.40.14) are the image-tag references used in Compose.

These references support the integration design; they do not substitute for importing the workflows into your own n8n instance or evaluating a downloaded local model.
