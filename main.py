from app.main import app

def expand_fmcg_abbreviations(text: str):
    m={"BTRM":"bathroom","CLNR":"cleaner","COOKIS":"cookie","CASHW":"cashew","JASMNE":"jasmine","CHOC":"chocolate"}
    return " ".join(m.get(t.upper(), t.lower()) for t in text.split())

def tokenize(text: str):
    import re
    stop={"with","and","the","for","inch","ml","kg","g","gm","mixed","colour","assorted","round"}
    brand={"harpic","samsung","colgate","vkc","horlicks","camlin"}
    toks=[t.lower() for t in re.findall(r"[a-zA-Z0-9]+", expand_fmcg_abbreviations(text))]
    return [t for t in toks if t not in stop and t not in brand and not t.isdigit()]

def detect_category_restrictions(tokens):
    s=set(tokens)
    if {"tooth","paste"}.issubset(s): return ["33"]
    if {"note","book"}.issubset(s): return ["48"]
    if {"puja","oil"}.issubset(s): return ["15"]
    if {"fruit","juice"}.issubset(s): return ["22"]
    if {"edible","oil"}.issubset(s): return ["15"]
    return []

def build_hsn_prefix_clause(tokens):
    p={};c=[]
    if "laptop" in tokens: p["prefix_0"]="84%"; c.append("hsn_code LIKE :prefix_0")
    if {"note","book"}.issubset(set(tokens)): p["prefix_1"]="48%"; c.append("hsn_code LIKE :prefix_1")
    return " OR ".join(c), p

def split_query_fields(text):
    import re
    brand={"harpic","samsung","colgate","vkc","horlicks","camlin"}
    toks=[t.lower() for t in re.findall(r"[a-zA-Z0-9]+", expand_fmcg_abbreviations(text))]
    all_tokens=[t for t in toks if not t.isdigit()]
    return {"brand_tokens":[t for t in all_tokens if t in brand],"product_tokens":[t for t in all_tokens if t not in brand],"all_tokens":all_tokens}

def _build_candidate_lexical_index(query, rows):
    q=set(tokenize(query)); docs=[]
    for r in rows:
        d=set(tokenize(getattr(r,'description',''))); docs.append({"tokens":d,"overlap":len(q&d)})
    return {"query_tokens":q,"docs":docs}

def compute_inverted_index_score(query,row,lexical_index,doc_idx,base_db_score):
    q=lexical_index['query_tokens']; d=lexical_index['docs'][doc_idx]['tokens']; o=lexical_index['docs'][doc_idx]['overlap']
    b=0.0
    if 'jam' in q and 'jam' in d: b+=0.35
    if 'puja' in q and 'puja' in d: b+=0.35
    if 'oil' in q and 'oil' in d: b+=0.15
    return base_db_score+o*0.2+b

class MatchResult:
    def __init__(self, hsn_code='', match_method='none', confidence=0.0):
        self.hsn_code=hsn_code; self.match_method=match_method; self.confidence=confidence

async def _match_one(query, db):
    try:
        from app.services.db_matcher import match_query
        rows=await match_query(query, db, top_k=1)
        if rows:
            r=rows[0]; return MatchResult(str(r.get('hsn_code','')), str(r.get('method','db_matcher')), float(r.get('score',0.0)))
    except Exception:
        pass
    return MatchResult()
