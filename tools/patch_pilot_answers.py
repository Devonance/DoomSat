"""One-off patch: the pilot logs and combines typed answers (Choice + Noul) through decision_graph helpers."""
import ast

p = "ground/pilot.py"
s = open(p, encoding="utf-8").read()


def rep(old, new):
    global s
    assert old in s, old[:80]
    s = s.replace(old, new, 1)


rep('''        cargs = dg.control_args(answers, cfg, t)''', '''        cargs = dg.control_args(answers, cfg, t, self.nav_memory)''')
rep('''        self.pending_turn, self.pending_turn_t, self.angle_at_cmd = 0.0, 0.0, None''',
    '''        self.pending_turn, self.pending_turn_t, self.angle_at_cmd = 0.0, 0.0, None
        self.nav_memory = {}''')
rep('''               "answers": {k: v.get("choice") for k, v in answers.items()},
               "confidence": {k: round(v.get("confidence", 0.0), 2) for k, v in answers.items()},''',
    '''               "answers": {k: dg.answer_label(v) for k, v in answers.items()},
               "confidence": {k: round(dg.answer_confidence(v), 2) for k, v in answers.items()},
               "probabilities": {k: {o: round(float(pv), 2) for o, pv in (v.get("probabilities") or {}).items()} for k, v in answers.items() if v.get("probabilities")},''')
rep('''                             "Controls": " ".join(f"{k}={v['choice']}" for k, v in answers.items())})''',
    '''                             "Controls": " ".join(f"{k}={dg.answer_label(v)}" for k, v in answers.items())})''')
rep('''            print(f"[pilot] #{n} jev {row['latency_ms']} ms cmd {row['cmd_ms']} ms  hp={row['health']} goal={self.goal} "
                      f"{' '.join(f'{k}={v}' for k, v in row['answers'].items())}  frames ok={self.frames.complete} lost={self.frames.incomplete}", flush=True)''',
    '''            print(f"[pilot] #{n} jev {row['latency_ms']} ms cmd {row['cmd_ms']} ms  hp={row['health']} goal={self.goal} "
                      f"{' '.join(f'{k}={v}' for k, v in row['answers'].items())} -> {row['control']['move']}/{row['control']['turn']:.0f}  "
                      f"frames ok={self.frames.complete} lost={self.frames.incomplete}", flush=True)''')
rep('''            self.goal = "EXPLORE"
            lv = self.telemetry.get("LEVEL")''', '''            self.goal = "EXPLORE"
                self.nav_memory = {}
            lv = self.telemetry.get("LEVEL")''')
open(p, "w", encoding="utf-8", newline="\n").write(s)
ast.parse(s)
print("pilot answers ok")

# the OpenAI-compatible System One emulation must accept structured instructions/criteria and Nouls
p = "ground/providers.py"
s = open(p, encoding="utf-8").read()
rep('''        spec = {qid: {"question": q["instructions"]["question"], "options": {k: v["what"] for k, v in q["criteria"].items()}}
                for qid, q in questions.items()}
        prompt = ("You are a System One judge: answer every question with exactly one of its option names. "
                  "Reply with a JSON object mapping question id to the chosen option name and nothing else.\\n"
                  f"STATE:\\n{json.dumps(state)}\\nQUESTIONS:\\n{json.dumps(spec)}")''',
    '''        spec = {qid: {"type": q.get("type", "choice"), "instructions": q["instructions"], "criteria": q["criteria"]} for qid, q in questions.items()}
        prompt = ("You are a System One judge. For each choice question answer with exactly one of its option names; for each noul "
                  "question answer true or false. Reply with a JSON object mapping question id to the answer and nothing else.\\n"
                  f"STATE:\\n{json.dumps(state)}\\nQUESTIONS:\\n{json.dumps(spec)}")''')
rep('''        answers = {}
        for qid, q in questions.items():
            options = list(q["criteria"])
            c = picked.get(qid) if picked.get(qid) in options else options[0]
            answers[qid] = {"type": "choice", "choice": c, "confidence": 1.0, "probabilities": {o: float(o == c) for o in options}}''',
    '''        answers = {}
        for qid, q in questions.items():
            if q.get("type") == "noul":
                answers[qid] = {"type": "noul", "noul": 1.0 if picked.get(qid) in (True, "true", "yes") else 0.0}
                continue
            options = list(q["criteria"])
            c = picked.get(qid) if picked.get(qid) in options else options[0]
            answers[qid] = {"type": "choice", "choice": c, "confidence": 1.0, "probabilities": {o: float(o == c) for o in options}}''')
open(p, "w", encoding="utf-8", newline="\n").write(s)
ast.parse(s)
print("providers ok")
