"""IAM Z3 Python 工具函数库。

所有 operator/key 分类及条件兼容性检查集中在此。
LLM 只需 `from iam_z3_utils import *` 即可使用全部函数。
"""

from z3 import Or, And, Not, Implies


# ── 操作符分类 ──

STRING_OPS = {
    "stringequals", "stringnotequals", "stringmatch", "stringmatchnot",
    "stringequalsignorecase", "stringequalsnot", "stringmatchnot",
    "stringstartwith", "stringendwith", "stringlike",
    "stringequalsifexists", "stringmatchifexists",
}

NUMERIC_OPS = {
    "numericequals", "numericnotequals", "numericgreaterthan",
    "numericlessthan", "numericgreaterthanequals", "numericlessthanequals",
    "numericequalsnot", "numberinrange",
    "numericgreaterthanifexists",
}

DATE_OPS = {
    "dateequals", "datenotequals", "dateless", "dategreater",
    "dategreaterorequals", "datelessorequals",
    "dategreaterthan", "datelessthan", "dategreaterthanequals", "datelessthanequals",
    "timeequals", "timenotequals", "timeless", "timegreater",
}

BOOL_OPS = {"bool"}

IP_OPS = {"ipaddress", "ipaddressnot", "ipaddressifexists"}

NULL_OPS = {"null"}

MULTI_VALUE_OPS = {
    "forallvalues:stringequals", "forallvalues:stringnotequals",
    "forallvalues:stringmatch", "forallvalues:stringmatchnot",
    "forallvalues:stringequalsnot",
    "foranyvalue:stringequals", "foranyvalue:stringnotequals",
    "foranyvalue:stringmatch", "foranyvalue:stringmatchnot",
    "foranyvalue:stringequalsnot",
}


# ── 键分类 ──

STRING_KEYS = {
    "g:PrincipalType", "g:PrincipalAccount", "g:PrincipalUrn", "g:PrincipalOrgId",
    "g:EnterpriseProjectId", "g:UserName", "g:SourceIdentity", "g:RequestedRegion",
    "g:SourceVpc", "g:UserAgent", "g:Referer",
    "g:CalledVia", "g:CalledViaFirst", "g:CalledViaLast",
    "g:TagKeys",
    "ServiceAgency", "g:SourceIdentity",
}

NUMERIC_KEYS = {"g:MFAAge", "g:MfaAge"}

BOOL_KEYS = {
    "g:MFAPresent", "g:SecureTransport", "g:PrincipalIsRootUser",
    "g:ViaService", "g:MfaPresent", "g:mfaPresent",
}

DATE_KEYS = {"g:CurrentTime", "g:TokenIssueTime"}

IP_KEYS = {"g:SourceIp", "g:VpcSourceIp"}

STRING_KEY_PREFIXES = (
    "g:RequestTag/", "g:PrincipalTag/", "g:ResourceTag/",
)


# ── 操作符分类函数 ──

def operator_is_string(op):
    return Or(*[op == v for v in STRING_OPS])


def operator_is_numeric(op):
    return Or(*[op == v for v in NUMERIC_OPS])


def operator_is_date(op):
    return Or(*[op == v for v in DATE_OPS])


def operator_is_bool(op):
    return op == "bool"


def operator_is_ip(op):
    return Or(*[op == v for v in IP_OPS])


def operator_is_null(op):
    return op == "null"


# ── 键分类函数 ──

def key_is_string(k):
    return Or(*[k == v for v in STRING_KEYS])


def key_is_numeric(k):
    return Or(*[k == v for v in NUMERIC_KEYS])


def key_is_bool(k):
    return Or(*[k == v for v in BOOL_KEYS])


def key_is_date(k):
    return Or(*[k == v for v in DATE_KEYS])


def key_is_ip(k):
    return Or(*[k == v for v in IP_KEYS])


# ── 条件兼容性 ──

def condition_compatible(has_cond, op, key):
    """条件操作符必须与键的类型匹配（null 操作符兼容任意键）。"""
    return Implies(
        And(has_cond, Not(operator_is_null(op))),
        Or(
            And(operator_is_string(op), key_is_string(key)),
            And(operator_is_numeric(op), key_is_numeric(key)),
            And(operator_is_bool(op), key_is_bool(key)),
            And(operator_is_date(op), key_is_date(key)),
            And(operator_is_ip(op), key_is_ip(key)),
        ),
    )
