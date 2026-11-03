# Lore and fight specs from the Ghosts'n Goblins wiki

Collected from <https://ghostsngoblins.fandom.com/wiki/> (the Demon's Crest
pages) and kept here because it is the only source that states **how the fights
actually work** — the ROM gives us sprites and hitboxes, not intent. Raw wikitext
is cached in `captures/wiki/` (git-ignored); re-fetch with
`python3 tools/fetch_wiki_lore.py`.

## Story, in the game's own order

Six crests — Earth, Wind, Fire, Water, Time and Heaven — fell into the Demon
Realm, and the demons fought a Crest War over them. Firebrand, the Red Demon,
claimed five of them, then killed the demon dragon **Somulo** for the Crest of
Heaven — mortally wounded in the process. **Phalanx** ambushed the wounded
Firebrand, took every crest and sealed him.

Phalanx's stolen power summoned the Crest of Infinity, but the Crest of Fire had
been damaged in the Somulo fight (Firebrand kept a shard), so it shattered and the
Demon Realm burned. Phalanx then blamed Firebrand, cast himself as the saviour and
became the "White King", ruler of both realms. Years later he hands Firebrand a
piece of the Crest of Fire, lets him escape the colosseum, and sends his general
**Arma** after him.

That is the frame for our port: the colosseum (area 0) is the tutorial boss, and
**Somulo there is the corpse** of the dragon Firebrand already killed — a rotting
dragon kept as a spectacle. It explains the "eyes closed" walk mechanically: he
is not blindfolded, he is undead.

## Boss roster (what each fight *is*)

| Boss | Where | Species in the port | How the fight works |
|---|---|---|---|
| **Somulo** | Colosseum, prologue | `$33` (area 0) | Chases Firebrand and smashes with claws; at a dead end switches to fireballs whose ground impact spreads into a fire wave; **only lowers his head to fire when Firebrand is on the ground**; after enough damage he faints, recovers as the player escapes, gets **stuck in the small door** with only his head out, still firing — **3 more hits** burn the head. |
| **Arma** | stage I end, stage IV, later | `$A5` flags 0/2/4 | Fought **three times, each with different tactics**; first fight uses the Crest of Earth and ends with him escaping and **dropping the crest**. |
| **Grewon** | 6-A Palace of Decadence; Snowy Barrens | `$13` | Jumps at you fast from off-screen; **poisons if you fly low over it**; when hit it glows **green** and stands still, and hitting it again triggers a **counter-leap that reaches you anywhere**. Weak to the **Crest of Time**. Drops the last Fire crest piece; the Palace version drops a full heal. |
| **Flame Lord** | Forest Fire stage | `$58` | Two phases. Phase 1 is a burning skeleton torso that throws **two fire birds**; the birds gather, ignite the forest, and he forms from where they converge. |
| **Ovnunu** | | `$16` | A pile of sludge with eyes: rises, stops, then **shoots its eyes out**. The big eye only exposes itself once the small ones are gone. |
| **Hippogriff** | Towers of Doom (Gryphon Spire) | — | Dormant as a **statue**: headbutt it to wake it, then it **fires feathers** and **dashes**. |
| **Scula** | | `$7B` + `$7C` | Two linked species (the two halves). |
| **Holothurion** | Poseidonia | `$6F` | |
| **Crawler** | | `$82` | |
| **Phalanx** | final | `$86` → `$8D` | Main antagonist; first his own power, then the **Crest of Heaven**; the second form is the powered-up one. |
| **Dark Demon** | secret stage | `$BC` | Secret boss, unlocked with the Crest of Infinity + password. Two forms — one of **bones**, one **demonic** — morphing between them. Older than the Crest War; even Phalanx could not handle it. |

## Shops and NPCs (dialogue and price spec)

**The Black Lotus** — potion shop, run by **Phorapa**, in the Stage II town. Every
potion also needs an **Urn** to hold it.

| Potion | Price |
|---|---|
| Mercury | 6 G.P. |
| Sulfur | 10 G.P. |
| Herb | 25 G.P. |
| Elixir | 100 G.P. |
| Ginseng | 140 G.P. |

**The Wise Man** — spell shop, run by **Morack**. Every spell needs a **Vellum**.

| Spell | Price |
|---|---|
| Shadow | 10 G.P. |
| Hold | 20 G.P. |
| Imp | 25 G.P. |
| Shock | 50 G.P. |
| Death | 80 G.P. |

**Malwous** — old demon at the town entrance; explains the equipped **talisman**
(Crown = more money, Skull = more soul energy, Armor = less knockback, Fang = …).
He sells nothing, but his room's pots can be broken.

**Vagrant** — hub-world NPC who does **not recognise Firebrand's normal form**,
only his legendary one, and gives **different advice depending on the equipped
crest**. Sample lines: with the Crest of Fire he warns that "the red demon
Firebrand has risen… if Phalanx had not rescued us we would all be dead"; with the
Crest of Earth he notes "the General was wearing a uniform something like yours".
So his dialogue is gated on the crest, not on story progress.

**Trio the Pago** — headbutt minigame, three hidden locations on the map (easy
tile, forest island, small lake). Pay a fee, pick a difficulty, BGM changes, and
smash a required number of skulls out of wall holes before the timer runs out.
Best played with the **Crown** talisman equipped.

## The secret and the retail password

Dark Demon is unlocked by: collect every item (except the Crest of Infinity), beat
**all three of Phalanx's forms** for the third ending, and then a code appears:

**`QFFF KNRR DDLR XGTQ`**

Entered in the password menu, it returns the player to the game **holding the
Crest of Infinity** and opens the extra stage.

This is the first **verified retail-format password** we have, and it does not
look like our 10-letter codec: the retail code is **16 characters in four groups
of four**. That is a concrete test vector for the retail password work — either
our codec learns to produce/accept this shape, or it is a different system.

## Port status against this

- Implemented: Somulo (area 0), Arma ×3, Scula, Holothurion, Ovnunu, Crawler,
  Phalanx (2 forms), Flame Lord, Dark Demon, Grewon's green invulnerability tell.
- Named maps already extracted: `black_lotus`, `wise_man`, `library`,
  `demons-hideout-the-dark-demon`, all 34 stage maps.
- Not yet implemented from this source: Somulo's four-beat fight (chase, fire
  wave, faint, stuck head), Grewon's counter-leap rule, Hippogriff's statue
  wake-up, Flame Lord's fire-bird phase, Ovnunu's eye mechanic, the two shops'
  price/Urn/Vellum rules, Vagrant's crest-gated dialogue, Trio the Pago.
