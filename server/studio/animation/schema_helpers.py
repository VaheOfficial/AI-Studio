"""Shared parameter-schema primitives for declarative render components."""
F={'type':'number','minimum':0,'maximum':1}
C={'type':'string','pattern':r'^(#[0-9a-fA-F]{6}|\$(background|ink|accent|secondary|muted|paper|line|glow))$'}
B={'type':'boolean'}
def enum(*values):return {'type':'string','enum':list(values)}
def schema(properties,required=()):return {'type':'object','properties':properties,'required':list(required),'additionalProperties':False}
