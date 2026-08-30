# Fixture declaration for place.py selfcheck. `{ROOT}` is replaced with a
# temporary directory; nothing here is a real machine path.

<!-- BEGIN SITES TSV -->
```tsv
id	host	user	home	reach	launch
S1	local	tester	{ROOT}/home	local	
S2	remote	nobody	{ROOT}/unreachable	absent	no /mnt/c
```
<!-- END SITES TSV -->

<!-- BEGIN WORKSPACES TSV -->
```tsv
id	site	kind	path	extra
W1	S1	direct	{ROOT}/ws	
```
<!-- END WORKSPACES TSV -->

<!-- BEGIN LOCATIONS TSV -->
```tsv
id	scope	anchor	tool	requirement	reason	legacy
L-claude-home	home	S1	claude	required		
L-claude-ws	workspace	W1	claude	required		unmanaged.md
L-cursor-ws	workspace	W1	cursor-agent	required		
L-agy-ws	workspace	W1	agy	absent	not used here	
L-opencode-ws	workspace	W1	opencode	required		
L-s2	home	S2	claude	absent	site is absent	
```
<!-- END LOCATIONS TSV -->

<!-- BEGIN EXCEPTIONS TSV -->
```tsv
rule	location_id	requirement	reason
alpha	L-claude-home	absent	home overlay is private
```
<!-- END EXCEPTIONS TSV -->
