# ACK Area File Specification (from `src` loader/saver behavior)

This document specifies the ACK area file format as actually implemented by the engine (loader in `src/db.c`, writer in `src/areasave.c`), including backward-compatibility and runtime quirks.

## 1) Boot-time container format

Area files are discovered from `area/area.lst` and read section-by-section.

- Each section starts with `#<SECTION_NAME>`.
- Each area file ends with `#$`.
- The loader accepts these section names:
  - `AREA`
  - `HELPS`
  - `MOBILES`
  - `MOBPROGS`
  - `OBJECTS`
  - `RESETS`
  - `ROOMS`
  - `SHOPS`
  - `SPECIALS`
  - `OBJFUNS`

Unknown section names are fatal during boot.

---

## 2) `#AREA` header section

### 2.1 Required first line

Immediately after `#AREA`, the first line is the area display name as a `~`-terminated string.

### 2.2 Optional tagged header records

After name, the loader reads tagged records one leading letter at a time until the next `#` token is encountered.

Supported tags:

- `F <number>`: reset rate (minutes/ticks domain used by game loop)
- `O <string~>`: owner
- `Q <number>`: area revision/version used for compatibility logic
- `U <string~>`: area reset message
- `R <string~>`: read ACL expression
- `W <string~>`: write ACL expression
- `P <text...>`: marks pay area flag (rest of line ignored)
- `M <text...>`: marks no-room-affect flag (rest of line ignored)
- `X <number>`: vnum offset
- `V <min_vnum> <max_vnum>`
- `N <number>`: explicit area slot/index
- `T <text...>`: teleport-allowed area flag
- `B <text...>`: building/in-progress flag
- `S <text...>`: hide-on-areas-list flag
- `K <string~>`: area keyword
- `L <string~>`: area level label
- `I <min_level> <max_level>`

### 2.3 Defaults when omitted

If a tag is not present, defaults are applied in memory before parsing optionals:

- reset rate `15`
- owner empty
- read/write ACLs `"all"`
- level label `{?? ??}`
- keyword `none`
- reset message `You hear the screams of the Dead within your head.`
- min/max level `0/0`
- min/max vnum `0/MAX_VNUM`
- area flags cleared
- area revision starts as `-1`

If `N` is omitted or 0, boot assigns the first unused area slot.

---

## 3) `#HELPS` section

Record format:

```
<level> <keyword~>
<text~>
```

Section terminator:

```
0 $~
```

Notes:

- `keyword` beginning with `$` ends parsing.
- Text can be prefixed with `.` by the saver when first char would otherwise be whitespace.

---

## 4) `#MOBILES` section

A mobile block starts with `#<vnum>` and ends implicitly when the next mobile starts, then terminates with `#0`.

### 4.1 Core mobile block

```
#<vnum>
<player_name~>
<short_descr~>
<long_descr~>
<description~>
<act_flags> <affected_by_flags> <alignment> S
<level> <sex>
<ac_mod> <hr_mod> <dr_mod>
```

Important behaviors:

- Loader forces `ACT_IS_NPC` on all mobiles.
- Loader uppercases first character of long and full descriptions.
- `level` is passed through `number_fuzzy()` at load time.

#### 4.1.1 Core numeric field semantics

- `act_flags`: NPC behavior bitvector (`ACT_*`) controlling aggression, hunting, sentinel behavior, training/practice availability, intelligence hooks, etc.
- `affected_by_flags`: starting affect bitvector (`AFF_*`) applied to spawned instances.
- `alignment`: integer alignment value used by combat/spell/social logic.
- `sex`: enum (`SEX_NEUTRAL`, `SEX_MALE`, `SEX_FEMALE`).
- `ac_mod`, `hr_mod`, `dr_mod`: direct NPC combat modifiers feeding `GET_AC`, `GET_HITROLL`, `GET_DAMROLL`; these are additive on top of derived/base values and materially change hit chance and damage.

### 4.2 Extended mobile stats (`!` line)

If next token is `!`, loader consumes:

```
! <class> <clan> <race> <position> <skills> <cast> <def>
```

Runtime nuance: loader sets position to standing and still reads/discards stored position field.

Compatibility nuance:

- If area revision `< 16` or race is negative, race is coerced to default (build-dependent compile switch path).

#### 4.2.1 Semantic meaning of each `!` value

- `class`: numeric index into `class_table` / remort class flow (e.g., Mage/Cleric/Thief/Warrior/Psionicist in stock data). For NPCs this drives class-based logic and skill lookups where class is consulted.
- `clan`: numeric clan index (`clan_table`). Commonly 0/none unless mob is tied to clan logic/rooms/equipment.
- `race`: numeric index into `race_table`; influences racial modifiers and default realm affinities used by damage code.
- `position`: persisted by saver but ignored at runtime on load for prototypes; spawned NPCs are forced to `POS_STANDING`.
- `skills`: bitvector of combat maneuvers (`MOB_*` flags), such as extra attacks, disarm/trip, dodge/parry, martial/enhanced, dirt, charge.
- `cast`: bitvector of offensive auto-cast spells (`CAST_*` flags). During combat rounds, NPC AI iterates these bits and may cast one spell if mana/chance checks pass.
- `def`: bitvector of defensive/self-preservation casting (`DEF_*` flags). Used for self-healing in combat and shield upkeep out of combat.

#### 4.2.2 Practical combat impact of `skills`, `cast`, `def`

- `skills` affects combat behavior and also contributes to mob XP valuation (many bits add multipliers in `exp_for_mobile`).
- `cast` drives offensive spell attempts in the fight update loop; chance scales by pseudo-level and each enabled bit maps to a spell name.
- `def` enables heal tiers (`cure light` -> `heal`) and shield spells (`fireshield`, `iceshield`, `shockshield`) when conditions are met.

### 4.3 Resistance/power tuple (`|` line)

If next token is `|`, loader consumes:

```
| <strong_magic> <weak_magic> <race_mods> <power_skills> <power_cast> <resist> <suscept>
```

#### 4.3.1 Semantic meaning of each `|` value

- `strong_magic`: bitvector of magic realms this mob is naturally strong with.
- `weak_magic`: bitvector of realms this mob is weak with.
- `race_mods`: race-modifier bitvector (fast/slow heal, strong/weak/no magic, poison immunity, size/body mods, skin mods, etc.).
- `power_skills`: secondary skill bitvector channel (same vocabulary as `skills`).
- `power_cast`: secondary cast bitvector channel (same vocabulary as `cast`).
- `resist`: realm-resistance bitvector used by spell damage handling.
- `suscept`: realm-susceptibility bitvector used by spell damage handling.

Implementation note: `power_skills` and `power_cast` are loaded/saved and editable, but in this codebase the active combat loop primarily consumes `skills` and `cast`; power fields are best treated as reserved/extension channels unless your fork wires them into runtime behavior.

#### 4.3.2 Realm and race-mod bit namespaces

- Realm bitvectors (`strong_magic`, `weak_magic`, `resist`, `suscept`) use the same domain as `tab_magic_realms` / `REALM_*` (fire, shock, light, gas, poison, cold, sound, acid, drain/negation, impact, mind/psionic, holy).
- `race_mods` uses `RACE_MOD_*` bits (e.g., `STRONG_MAGIC`, `WEAK_MAGIC`, `NO_MAGIC`, `IMMUNE_POISON`, `WOODLAND`, `DARKNESS`, size and skin variants).

### 4.4 Inline mobprogs in mobile block

If next token is `>`, inline mobprog entries are parsed until `|` line terminator:

```
><prog_type_name> <arglist~>
<comlist~>
...
|
```

Supported names map to internal types:

- `in_file_prog`
- `act_prog`
- `speech_prog`
- `rand_prog`
- `fight_prog`
- `hitprcnt_prog`
- `death_prog`
- `entry_prog`
- `greet_prog`
- `all_greet_prog`
- `give_prog`
- `bribe_prog`

Section terminator for mobiles is `#0`.

---

## 5) `#MOBPROGS` section (external file references)

This section binds mobiles to mobprog files.

Record:

```
M <mob_vnum> <filename>
```

Section terminator:

```
S
```

Comments beginning with `*` are accepted.

When loaded, referenced files are opened from mobprog directory and parsed as mobprog entries (`>` ... `|`) similar to inline definitions.

---

## 6) `#OBJECTS` section

Object blocks begin at `#<vnum>` and section ends at `#0`.

### 6.1 Core object block

```
#<vnum>
<name~>
<short_descr~>
<description~>
<item_type> <extra_flags> <wear_flags> <item_apply>
<value0> <value1> <value2> <value3> <value4> <value5> <value6> <value7> <value8> <value9>
<weight>
```

Legacy compatibility:

- For revisions `< 15`, wear flags are read from old encoding and converted through `convert_wearflags[]`.
- For revisions `< 15`, values 4..9 are not read and are forced to 0.

Hardcoded load tweak:

- Potions get `ITEM_NODROP` forced at load.

### 6.2 Optional object subrecords

After weight, loader accepts repeated option records until unknown letter:

- `A`
  - `<location> <modifier>`
  - Creates an apply affect (`type=-1`, `duration=-1`, bitvector 0).
- `E`
  - `<keyword~>`
  - `<description~>`
- `L`
  - `<level>`

### 6.3 Spell slot translation

On load, slot numbers in object values are translated to internal skill numbers:

- Pills/Potions/Scrolls: values 1,2,3 use `slot_lookup`
- Wands/Staffs: value 3 uses `slot_lookup`

On save, this conversion is reversed to slot IDs (`skill_table[sn].slot`).

---

## 7) `#ROOMS` section

Room blocks begin at `#<vnum>`, end per-room at `S`, and section ends at `#0`.

### 7.1 Core room block

```
#<vnum>
<name~>
<description~>
<room_flags> <sector_type>
```

Behavior:

- `SECT_NULL` is coerced to `SECT_INSIDE`.
- Room affects initialize empty.
- Door array is 0..5 only.

### 7.2 Exit records (`D`)

```
D<door_number>
<description~>
<keyword~>
<locks> <key_vnum> <to_room_vnum>
```

Door must be 0..5.

`locks` behavior:

- New-style areas store bitvector-like exit flags (with closed/locked bits filtered out by saver).
- Legacy special case: if loaded `locks == 2`, interpreted as `EX_ISDOOR | EX_PICKPROOF`.

### 7.3 Extra descriptions (`E`)

```
E
<keyword~>
<description~>
```

### 7.4 End-of-room marker

```
S
```

---

## 8) `#SHOPS` section

One line per shop:

```
<keeper_mob_vnum> <buy_type1> <buy_type2> <buy_type3> <buy_type4> <buy_type5> <profit_buy> <profit_sell> <open_hour> <close_hour>
```

Section terminator:

```
0
```

`MAX_TRADE` is 5, so exactly five buy-type fields are consumed.

---

## 9) `#SPECIALS` section

Assigns special procedures to mobiles.

Record:

```
M <mob_vnum> <spec_fun_name>
```

Section terminator:

```
S
```

`*` comment lines are accepted.

Unknown special names log bug entries but parsing continues.

---

## 10) `#OBJFUNS` section

Assigns object functions.

Record:

```
O <obj_vnum> <obj_fun_name>
```

Section terminator:

```
S
```

If referenced object vnum is missing, loader logs an error and consumes the function token to stay in sync.

---

## 11) `#RESETS` section

Resets are parsed into area reset list and also attached to the current room reset list (OLC convenience).

General record shape:

```
<command> <ifflag> <arg1> <arg2> [arg3] <notes...>
```

For commands `G` and `R`, loader does **not** read `arg3`; it is forced to 0 and remaining text is notes.

Section terminator:

```
S
```

Comment lines starting with `*` are accepted.

### 11.1 Recognized commands at load

- `A`: obsolete; discarded
- `M`: load mobile; requires valid room in `arg3`; sets "last mob room"
- `O`: load object in room; requires valid room in `arg3`; sets "last obj room"
- `P`: treated obsolete/inactive path (not linked)
- `G`, `E`: give/equip object to last mob room context
- `D`: set door state; room in `arg1`
- `R`: randomize exits; room in `arg1`

Reset acceptance is context-sensitive (`last_mob_room` state for `G`/`E`).

### 11.2 Second-pass reset validation (`check_resets`)

After all areas load, a strict validation pass removes invalid resets and logs area bugs.
Checks include:

- Existence of referenced mob/object/room vnums.
- `D` requires valid door index 0..5 and an actual door exit with `EX_ISDOOR`.
- `D` lock state must be in 0..2.
- `R` exit index must be 0..5.

Invalid resets are unlinked from both area list and per-room reset list.

---

## 12) String and terminator conventions

- Most free-text fields are `fread_string` format (`...~`).
- Section markers and many control lines are single-letter control records.
- `#0` terminates `MOBILES`, `OBJECTS`, `ROOMS`.
- `S` terminates `MOBPROGS`, `SPECIALS`, `OBJFUNS`, `RESETS` (and each room body).
- `#HELPS` uses sentinel `0 $~`.

---

## 13) Save order and canonical output

Area saver emits sections in this order when present:

1. `#AREA`
2. `#HELPS`
3. `#ROOMS`
4. `#MOBILES`
5. `#MOBPROGS`
6. `#OBJECTS`
7. `#SHOPS`
8. `#RESETS`
9. `#SPECIALS`
10. `#OBJFUNS`
11. `#$`

It writes `Q 16` (`AREA_VERSION 16`) as current canonical revision.

---

## 14) Bitvectors/enums and human-readable tables

The area format stores many numeric fields as raw ints/bitvectors (mob flags, affect bits, room flags, wear flags, item types, sector types, etc.).

Human-facing names used by builders map through table sets in `src/buildtab.c`, notably:

- `tab_mob_flags`
- `tab_item_types`
- `tab_obj_flags`
- `tab_wear_flags`
- `tab_room_flags`
- `tab_sector_types`

At runtime, core defines for area flags, mobprog constants, room/object semantics, and reset-related constants are in `src/config.h`.

---

## 15) Practical authoring guidance (derived from parser behavior)

- Always include `Q 16` for newly authored areas.
- Use explicit `N`, `V`, `I`, and ACL tags in `#AREA`; avoid depending on defaults.
- Keep `#RESETS` after rooms/mobs/objs in source file for readability, but note loader tolerates cross-area references due to deferred `check_resets`.
- For doors, write real exit flag bitvectors; legacy lock value `2` has special backward meaning.
- Ensure any `G`/`E` resets follow an `M` reset contextually, or they may fail validation.
- If using external mobprogs, ensure files exist in mobprog directory and syntax uses `>` records terminated by `|`.

