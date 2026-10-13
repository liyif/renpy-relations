"""Rebuild the shipped Chinese font subset from a locally supplied Noto CJK font."""

import argparse
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-font", required=True, type=Path)
    parser.add_argument("--font-number", type=int, default=2, help="SC face in the standard Noto CJK collection")
    args = parser.parse_args()
    game = Path(__file__).resolve().parent / "game"
    text = "".join(p.read_text(encoding="utf-8") for p in game.glob("*.rpy"))
    text += (game / "content.json").read_text(encoding="utf-8")
    text += "".join(chr(i) for i in range(32, 127))
    characters = {ord(c) for c in text if not c.isspace()}
    characters.add(32)
    font = TTFont(args.source_font, fontNumber=args.font_number)
    missing = characters - set(font.getBestCmap())
    if missing:
        raise ValueError(f"Source font lacks characters: {''.join(chr(c) for c in sorted(missing))}")
    options = subset.Options()
    options.name_IDs = ["*"]
    options.name_languages = ["*"]
    subsetter = subset.Subsetter(options=options)
    subsetter.populate(unicodes=characters)
    subsetter.subset(font)
    names = {1: "Tidelight Sans", 3: "TidelightSans-Subset-Regular", 4: "Tidelight Sans Regular",
             6: "TidelightSans-Regular", 16: "Tidelight Sans", 21: "Tidelight Sans"}
    for record in font["name"].names:
        if record.nameID in names:
            record.string = names[record.nameID].encode(record.getEncoding())
    output = game / "fonts" / "tidelight.otf"
    output.parent.mkdir(parents=True, exist_ok=True)
    font.save(output)
    print(f"Built {output}: {len(characters)} characters, {output.stat().st_size} bytes")


if __name__ == "__main__":
    main()
