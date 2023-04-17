"""
Process Unicode
---------------

Module for processing Unicode based corpuses for autosuggestion and autocompletion generation.

Contents:
    gen_emoji_lexicon
"""


import csv
import fileinput
import json
import re
from importlib.resources import files

import emoji
from icu import Char, UProperty
from tqdm.auto import tqdm

from scribe_data.extract_transform.emoji_utils import get_emoji_codes_to_ignore
from scribe_data.load.update_utils import (
    add_num_commas,
    get_language_iso,
    get_path_from_et_dir,
)

from . import _resources

emoji_codes_to_ignore = get_emoji_codes_to_ignore()


def gen_emoji_lexicon(
    language="English",
    num_emojis=None,
    emojis_per_keyword=None,
    ignore_keywords=None,
    export_base_rank=False,
    update_local_data=False,
    verbose=True,
):
    """
    Generates a dictionary of keywords (keys) and emoji unicode(s) associated with them (values).

    Parameters
    ----------
        language : string (default=en)
            The language keywords are being generated for.

        num_emojis : int (default=None)
            The limit for number of emojis that keywords should be generated from.

        emojis_per_keyword : int (default=None)
            The limit for number of emoji keywords that should be generated per keyword.

        ignore_keywords : str or list (default=None)
            Keywords that should be ignored.

        export_base_rank : bool (default=False)
            Whether to export whether the emojis is a base character as well as its rank.

        update_local_data : bool (default=False)
            Saves the created dictionaries as JSONs in the local formatted_data directories.

        verbose : bool (default=True)
            Whether to show a tqdm progress bar for the process.

    Returns
    -------
        Keywords dictionary for emoji keywords-to-unicode are saved locally or uploaded to Scribe apps.
    """

    keyword_dict = {}

    iso = get_language_iso(language)

    if isinstance(ignore_keywords, str):
        keywords_to_ignore = [ignore_keywords]
    elif isinstance(ignore_keywords, list):
        keywords_to_ignore = ignore_keywords
    else:
        keywords_to_ignore = []

    keywords_to_ignore = [k.lower() for k in keywords_to_ignore]

    # Pre-set up the emoji popularity data.
    popularity_dict = {}

    with files(_resources).joinpath("2021_ranked.tsv").open() as popularity_file:
        tsv_reader = csv.DictReader(popularity_file, delimiter="\t")
        for tsv_row in tsv_reader:
            popularity_dict[tsv_row["Emoji"]] = int(tsv_row["Rank"])

    # Pre-set up handling flags and tags (subdivision flags).
    # emoji_flags = Char.getBinaryPropertySet(UProperty.RGI_EMOJI_FLAG_SEQUENCE)
    # emoji_tags = Char.getBinaryPropertySet(UProperty.RGI_EMOJI_TAG_SEQUENCE)
    # regexp_flag_keyword = re.compile(r".*\: (?P<flag_keyword>.*)")

    path_to_scribe_org = get_path_from_et_dir()
    annotations_file_path = f"{path_to_scribe_org}/Scribe-Data/node_modules/cldr-annotations-full/annotations/{iso}/annotations.json"
    annotations_derived_file_path = f"{path_to_scribe_org}/Scribe-Data/node_modules/cldr-annotations-derived-full/annotationsDerived/{iso}/annotations.json"

    cldr_file_paths = {
        "annotations": annotations_file_path,
        "annotationsDerived": annotations_derived_file_path,
    }

    for cldr_file_key, cldr_file_path in cldr_file_paths.items():
        with open(cldr_file_path, "r") as file:
            cldr_data = json.load(file)

        cldr_dict = cldr_data[cldr_file_key]["annotations"]

        for cldr_char in tqdm(
            iterable=cldr_dict,
            desc=f"Characters processed from '{cldr_file_key}' CLDR file for {language}",
            unit="cldr characters",
            disable=not verbose,
        ):
            # Filter CLDR data for emoji characters while not including certain emojis.
            if (
                cldr_char in emoji.EMOJI_DATA
                and cldr_char.encode("utf-8") not in emoji_codes_to_ignore
            ):
                emoji_rank = popularity_dict.get(cldr_char)

                # If number limit specified, filter for the highest-ranked emojis.
                if num_emojis and (emoji_rank is None or emoji_rank > num_emojis):
                    continue

                # Process for emoji variants.
                has_modifier_base = Char.hasBinaryProperty(
                    cldr_char, UProperty.EMOJI_MODIFIER_BASE
                )
                if has_modifier_base and len(cldr_char) > 1:
                    continue

                # Only fully-qualified emoji should be generated by keyboards.
                # See www.unicode.org/reports/tr51/#Emoji_Implementation_Notes.
                if (
                    emoji.EMOJI_DATA[cldr_char]["status"]
                    == emoji.STATUS["fully_qualified"]
                ):
                    emoji_annotations = cldr_dict[cldr_char]

                    # # Process for flag keywords.
                    # if cldr_char in emoji_flags or cldr_char in emoji_tags:
                    #     flag_keyword_match = regexp_flag_keyword.match(
                    #         emoji_annotations["tts"][0]
                    #     )
                    #     flag_keyword = flag_keyword_match.group("flag_keyword")
                    #     keyword_dict.setdefault(flag_keyword, []).append(
                    #         {
                    #             "emoji": cldr_char,
                    #             "is_base": has_modifier_base,
                    #             "rank": emoji_rank,
                    #         }
                    #     )

                    for emoji_keyword in emoji_annotations["default"]:
                        emoji_keyword = emoji_keyword.lower()  # lower case the key
                        if (
                            # Use single-word annotations as keywords.
                            len(emoji_keyword.split()) == 1
                            and emoji_keyword not in keywords_to_ignore
                        ):
                            keyword_dict.setdefault(emoji_keyword, []).append(
                                {
                                    "emoji": cldr_char,
                                    "is_base": has_modifier_base,
                                    "rank": emoji_rank,
                                }
                            )

    # Check nouns files for plurals and update their data with the emojis for their singular forms.
    with open(f"./{language}/formatted_data/nouns.json", encoding="utf-8") as f:
        noun_data = json.load(f)

    plurals_to_singulars_dict = {
        noun_data[row]["plural"].lower(): row.lower()
        for row in noun_data
        if noun_data[row]["plural"] != "isPlural"
    }

    for plural, singular in plurals_to_singulars_dict.items():
        if plural not in keyword_dict and singular in keyword_dict:
            keyword_dict[plural] = keyword_dict[singular]

    # Sort by rank after all emojis already found per keyword.
    for emojis in keyword_dict.values():
        emojis.sort(
            key=lambda suggestion: float("inf")
            if suggestion["rank"] is None
            else suggestion["rank"]
        )

        # If specified, enforce limit of emojis per keyword.
        if emojis_per_keyword and len(emojis) > emojis_per_keyword:
            emojis[:] = emojis[:emojis_per_keyword]

    total_keywords = add_num_commas(num=len(keyword_dict))

    if verbose:
        print(
            f"Number of emoji trigger keywords found for {language}: {total_keywords}"
        )

    # Remove base status and rank if not needed.
    if not export_base_rank:
        keyword_dict = {
            k: [{"emoji": emoji_keys["emoji"]} for emoji_keys in v]
            for k, v in keyword_dict.items()
        }

    if update_local_data:
        path_to_formatted_data = (
            get_path_from_et_dir()
            + f"/Scribe-Data/src/scribe_data/extract_transform/{language.capitalize()}/formatted_data/emoji_keywords.json"
        )

        with open(path_to_formatted_data, "w", encoding="utf-8") as file:
            json.dump(keyword_dict, file, ensure_ascii=False, indent=0)

        print(
            f"Emoji keywords for {language} generated and saved to '{path_to_formatted_data}'."
        )

        path_to_data_table = (
            get_path_from_et_dir()
            + "/Scribe-Data/src/scribe_data/load/_update_files/data_table.txt"
        )

        for line in fileinput.input(path_to_data_table, inplace=True):
            if line.split("|")[1].strip() == language.capitalize():
                line = (
                    "|".join(line.split("|")[:-2])
                    + "|"
                    + total_keywords.rjust(len(" Emoji Keywords") - 1, " ")
                    + " |\n"
                )

            print(line, end="")

        path_to_total_data = (
            get_path_from_et_dir()
            + "/Scribe-Data/src/scribe_data/load/_update_files/total_data.json"
        )

        with open(path_to_total_data, encoding="utf-8") as f:
            current_data = json.load(f)

        current_data[language.capitalize()]["emoji_keywords"] = len(keyword_dict)
        with open(path_to_total_data, "w+", encoding="utf-8") as f:
            json.dump(current_data, f, ensure_ascii=False, indent=0)

    return keyword_dict
