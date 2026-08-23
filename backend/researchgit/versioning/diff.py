from dataclasses import dataclass, asdict
from difflib import SequenceMatcher
import re

def paragraphs(text: str): return [p.strip() for p in re.split(r"\n\s*\n", text.strip()) if p.strip()]
def sentences(text: str): return re.split(r"(?<=[.!?])\s+", text)
@dataclass
class Change: kind: str; before: str|None; after: str|None; sentence_diff: list[dict]
def structural_diff(before: str, after: str) -> list[dict]:
    a,b=paragraphs(before),paragraphs(after); out=[]
    for tag,i1,i2,j1,j2 in SequenceMatcher(None,a,b,autojunk=False).get_opcodes():
        if tag=="equal": continue
        if tag=="delete": out += [asdict(Change("REMOVED",x,None,[])) for x in a[i1:i2]]
        elif tag=="insert": out += [asdict(Change("ADDED",None,x,[])) for x in b[j1:j2]]
        else:
            for old,new in zip(a[i1:i2],b[j1:j2]):
                ops=[]
                for t,x1,x2,y1,y2 in SequenceMatcher(None,sentences(old),sentences(new)).get_opcodes():
                    if t!="equal": ops.append({"kind":t.upper(),"before":" ".join(sentences(old)[x1:x2]),"after":" ".join(sentences(new)[y1:y2])})
                out.append(asdict(Change("MODIFIED",old,new,ops)))
            out += [asdict(Change("REMOVED",x,None,[])) for x in a[i1+min(i2-i1,j2-j1):i2]]
            out += [asdict(Change("ADDED",None,x,[])) for x in b[j1+min(i2-i1,j2-j1):j2]]
    return out
