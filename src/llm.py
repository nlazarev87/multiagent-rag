import os
import threading

CONTEXT = 4096
_llm = None
loaded = False
_load_lock = threading.Lock()
_run_lock = threading.Lock()


def load():
    global _llm, loaded
    if _llm is None:
        with _load_lock:
            if _llm is None:
                from llama_cpp import Llama, LlamaRAMCache
                model = Llama(
                    model_path=os.environ["LLM_MODEL_PATH"],
                    n_ctx=CONTEXT,
                    n_threads=int(os.environ.get("LLM_THREADS", max(1, (os.cpu_count() or 2) // 2))),
                    n_gpu_layers=0,
                    verbose=False,
                )
                model.set_cache(LlamaRAMCache(capacity_bytes=256 << 20))
                _llm = model
    loaded = True


def count_tokens(text):
    load()
    with _run_lock:
        return len(_llm.tokenize(text.encode("utf-8"), add_bos=False))


def complete(system, user, max_tokens=200, examples=()):
    load()
    messages = [{"role": "system", "content": system}]
    for question, reply in examples:
        messages += [{"role": "user", "content": question}, {"role": "assistant", "content": reply}]
    messages.append({"role": "user", "content": user})
    with _run_lock:
        reply = _llm.create_chat_completion(messages=messages, max_tokens=max_tokens, temperature=0.0)
    return reply["choices"][0]["message"]["content"].strip()
