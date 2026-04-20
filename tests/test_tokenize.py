import importlib
import importlib.util
import sys
from pathlib import Path


def _load_main_with_stubs():
    import types

    # Stub missing external dependencies for import-time execution
    sys.modules["fastapi"] = types.ModuleType("fastapi")
    fastapi = sys.modules["fastapi"]

    class _FastAPI:
        def __init__(self, *args, **kwargs):
            pass

        def add_middleware(self, *args, **kwargs):
            pass

        def get(self, *args, **kwargs):
            return lambda fn: fn

        def post(self, *args, **kwargs):
            return lambda fn: fn

        def on_event(self, *args, **kwargs):
            return lambda fn: fn

    fastapi.FastAPI = _FastAPI
    fastapi.Depends = lambda x=None: None
    fastapi.HTTPException = Exception
    fastapi.Header = lambda *args, **kwargs: None
    fastapi.Query = lambda *args, **kwargs: None

    sys.modules["fastapi.middleware"] = types.ModuleType("fastapi.middleware")
    sys.modules["fastapi.middleware.cors"] = types.ModuleType("fastapi.middleware.cors")
    sys.modules["fastapi.middleware.cors"].CORSMiddleware = object

    sys.modules["fastapi.security"] = types.ModuleType("fastapi.security")
    sys.modules["fastapi.security"].OAuth2PasswordRequestForm = type(
        "OAuth2PasswordRequestForm", (), {}
    )

    sys.modules["sqlalchemy"] = types.ModuleType("sqlalchemy")
    sqlalchemy = sys.modules["sqlalchemy"]
    sqlalchemy.select = lambda *args, **kwargs: None

    class _TypeStub:
        def __init__(self, *args, **kwargs):
            pass

    sqlalchemy.String = _TypeStub
    sqlalchemy.Float = _TypeStub
    sqlalchemy.Integer = _TypeStub
    sqlalchemy.Text = _TypeStub
    sqlalchemy.Boolean = _TypeStub
    sqlalchemy.DateTime = _TypeStub
    sqlalchemy.Numeric = _TypeStub
    sqlalchemy.Date = _TypeStub
    sqlalchemy.text = lambda *args, **kwargs: None

    sys.modules["sqlalchemy.ext.asyncio"] = types.ModuleType("sqlalchemy.ext.asyncio")
    sqlalchemy_ext_asyncio = sys.modules["sqlalchemy.ext.asyncio"]
    sqlalchemy_ext_asyncio.AsyncSession = type("AsyncSession", (), {})
    sqlalchemy_ext_asyncio.create_async_engine = lambda *args, **kwargs: object()

    sys.modules["sqlalchemy.orm"] = types.ModuleType("sqlalchemy.orm")
    sqlalchemy_orm = sys.modules["sqlalchemy.orm"]
    sqlalchemy_orm.DeclarativeBase = type("DeclarativeBase", (), {})

    class _MappedStub:
        def __getitem__(self, item):
            return self

    sqlalchemy_orm.Mapped = _MappedStub()
    sqlalchemy_orm.mapped_column = lambda *args, **kwargs: None
    sqlalchemy_orm.sessionmaker = lambda *args, **kwargs: None

    sys.modules["pydantic"] = types.ModuleType("pydantic")
    pydantic = sys.modules["pydantic"]
    pydantic.BaseModel = type("BaseModel", (), {})
    pydantic.field_validator = lambda *args, **kwargs: (lambda fn: fn)

    sys.modules["passlib"] = types.ModuleType("passlib")
    sys.modules["passlib.context"] = types.ModuleType("passlib.context")

    class _CryptContext:
        def __init__(self, *args, **kwargs):
            pass

        def hash(self, x):
            return x

        def verify(self, a, b):
            return True

    sys.modules["passlib.context"].CryptContext = _CryptContext

    sys.modules["jose"] = types.ModuleType("jose")
    sys.modules["jose"].jwt = type(
        "jwt", (), {"encode": staticmethod(lambda *args, **kwargs: "tok"), "decode": staticmethod(lambda *args, **kwargs: {"sub": "user"})}
    )
    sys.modules["jose"].JWTError = Exception

    file_path = Path(__file__).resolve().parent.parent / "main.py"
    if "main" in sys.modules:
        del sys.modules["main"]
    spec = importlib.util.spec_from_file_location("main", str(file_path))
    module = importlib.util.module_from_spec(spec)
    sys.modules["main"] = module
    spec.loader.exec_module(module)
    return module


def test_tokenize_filters_brand_names(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    main = _load_main_with_stubs()

    tokens = main.tokenize("Samsung LED TV 55 inch with remote")

    assert "samsung" not in tokens
    assert "remote" in tokens
    assert "led" in tokens


def test_expand_fmcg_abbreviations(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    main = _load_main_with_stubs()

    assert main.expand_fmcg_abbreviations("BTRM CLNR") == "bathroom cleaner"
    assert main.expand_fmcg_abbreviations("COOKIS") == "cookie"
    assert main.expand_fmcg_abbreviations("CASHW") == "cashew"
    assert main.expand_fmcg_abbreviations("JASMNE") == "jasmine"
    assert main.expand_fmcg_abbreviations("CHOC BAR") == "chocolate bar"
    assert main.expand_fmcg_abbreviations("normal text") == "normal text"


def test_detect_category_restrictions(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    main = _load_main_with_stubs()

    # Test high priority rules
    assert main.detect_category_restrictions(['tooth', 'paste']) == ['33']
    assert main.detect_category_restrictions(['note', 'book']) == ['48']
    assert main.detect_category_restrictions(['puja', 'oil']) == ['33']  # puja overrides oil

    # Test lower priority rules
    assert main.detect_category_restrictions(['edible', 'oil']) == ['15']

    # Test no restrictions
    assert main.detect_category_restrictions(['random', 'product']) == []


def test_laptop_does_not_map_to_notebook(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    main = _load_main_with_stubs()

    clause, params = main.build_hsn_prefix_clause(['laptop'])

    assert params.get('prefix_0') == '84%'
    assert '48%' not in params.values()
    assert 'notebook' not in clause


def test_enhanced_stopwords(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    main = _load_main_with_stubs()

    tokens = main.tokenize("mixed colour assorted round chocolate bar 500gm")

    # New stop words should be filtered out
    assert "mixed" not in tokens
    assert "colour" not in tokens
    assert "assorted" not in tokens
    assert "round" not in tokens

    # Valid tokens should remain
    assert "chocolate" in tokens
    assert "bar" in tokens
