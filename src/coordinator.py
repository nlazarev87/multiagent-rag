from langgraph.graph import END, StateGraph

from agents import MISSING, NO_ANSWER, UNCONFIRMED, answer_agent, check_agent, clarify_agent, search_agent, select_agent
from dialog import add_turn, get_dialog
from store import known

ATTEMPTS = 2


def run(query, dialog_id):
    def select(state):
        state["work"] = select_agent(state["query"], get_dialog(state["dialog_id"]))
        return state

    def clarify(state):
        state["clear"] = clarify_agent(state["query"], state["work"])
        return state

    def search(state):
        state["chunks"] = search_agent(state["clear"])
        return state

    def answer(state):
        state["attempts"] = state.get("attempts", 0) + 1
        state["answer"] = answer_agent(state["query"], state["clear"], state["chunks"], state["work"], state.get("feedback"))
        return state

    def check(state):
        verdict = check_agent(state["answer"], state["chunks"], state["query"], known)
        state["status"] = verdict["status"]
        state["feedback"] = verdict["feedback"]
        state["sources"] = verdict["sources"]
        return state

    def route(state):
        if state["status"] == UNCONFIRMED and state["attempts"] < ATTEMPTS:
            return "answer"
        return "finish"

    def finish(state):
        if state["status"] in (UNCONFIRMED, MISSING):
            state["answer"] = NO_ANSWER
            state["status"] = MISSING
            state["sources"] = []
        names = []
        for source in state["sources"]:
            if source["document_name"] not in names:
                names.append(source["document_name"])
        state["document_names"] = names
        add_turn(state["dialog_id"], {"query": state["query"], "answer": state["answer"], "document_names": names})
        return state

    graph = StateGraph(dict)
    for name, node in (("select", select), ("clarify", clarify), ("search", search), ("answer", answer), ("check", check), ("finish", finish)):
        graph.add_node(name, node)
    graph.set_entry_point("select")
    graph.add_edge("select", "clarify")
    graph.add_edge("clarify", "search")
    graph.add_edge("search", "answer")
    graph.add_edge("answer", "check")
    graph.add_conditional_edges("check", route, {"answer": "answer", "finish": "finish"})
    graph.add_edge("finish", END)
    out = graph.compile().invoke({"query": query, "dialog_id": dialog_id})
    return {
        "answer": out["answer"],
        "status": out["status"],
        "document_names": out["document_names"],
        "sources": out["sources"],
    }
