from processing.tagger import (
    calculate_tags,
    MULTIPLE,
    FALSE_POSITIVE,
    UNIDENTIFIED,
    MESSAGE,
    CONFIDENCE,
    DEFAULT_CONFIDENCE,
    PREDICTIONS,
    LABEL,
    TAG,
)
import json
import processing


class TestTagCalculations:
    TIME = -2

    conf = processing.Config
    conf.min_confidence = 0.4
    conf.min_tag_confidence = 0.8
    conf.max_tag_novelty = 0.6
    conf.min_tag_clarity = 0.1
    conf.min_tag_clarity_secondary = 0.05
    conf.ignore_tags = None

    def test_no_tracks(self):
        assert self.get_tags([]) == {}

    def test_one_false_positive_track(self):
        falsy = create_track(FALSE_POSITIVE)
        assert FALSE_POSITIVE in self.get_tags([falsy])

    def test_one_track(self):
        goodRatty = create_track("rat")
        assert self.get_tags([goodRatty]) == {"rat": {CONFIDENCE: 0.9}}

    # def test_ignores_short_not_great_track(self):
    #     shortRatty = create_track("rat", confidence=0.65)
    #     shortRatty["num_frames"] = 2
    #     assert self.get_tags([shortRatty]) == {}

    def test_one_track_middle_confidence(self):
        rat = create_track("rat", confidence=0.6)
        assert self.get_tags([rat]) == {UNIDENTIFIED: {CONFIDENCE: DEFAULT_CONFIDENCE}}
        assert rat[PREDICTIONS][0][MESSAGE] == "Low confidence - no tag"

    def test_only_ever_one_unidentified_tag(self):
        rat1 = create_track("rat", confidence=0.6)
        rat2 = create_track("rat", confidence=0.6)
        assert self.get_tags([rat1, rat2]) == {
            UNIDENTIFIED: {CONFIDENCE: DEFAULT_CONFIDENCE}
        }

    def test_one_track_poor_confidence(self):
        poorRatty = create_track("rat", confidence=0.3)
        assert self.get_tags([poorRatty]) == {
            UNIDENTIFIED: {CONFIDENCE: DEFAULT_CONFIDENCE}
        }
        assert poorRatty[PREDICTIONS][0][MESSAGE] == "Low confidence - no tag"

    def test_one_track_poor_clarity_gives_unidentified(self):
        poorRatty = create_track("rat", clarity=0.02)
        assert self.get_tags([poorRatty]) == {
            UNIDENTIFIED: {CONFIDENCE: DEFAULT_CONFIDENCE}
        }
        assert (
            poorRatty[PREDICTIONS][0][MESSAGE]
            == "Confusion between two classes (similar confidence)"
        )

    def test_one_track_high_novelty_gives_unidentified(self):
        poorRatty = create_track("rat", novelty=0.88)
        assert self.get_tags([poorRatty]) == {
            UNIDENTIFIED: {CONFIDENCE: DEFAULT_CONFIDENCE}
        }
        assert poorRatty[PREDICTIONS][0][MESSAGE] == "High novelty"

    def test_multi_track_same_animal_gives_only_one_tag(self):
        ratty1 = create_track("rat")
        ratty2 = create_track("rat", confidence=0.95)
        assert self.get_tags([ratty1, ratty2]) == {"rat": {CONFIDENCE: 0.95}}

    def test_multi_track_different_animal_tags_both(self):
        ratty = create_track("rat")
        hedgehog = create_track("hedgehog", confidence=0.95)
        assert self.get_tags([ratty, hedgehog]) == {
            "rat": {CONFIDENCE: 0.9},
            "hedgehog": {CONFIDENCE: 0.95},
        }

    def test_multi_track_different_animal_poor_middle_confidence_tags_unidentified(
        self,
    ):
        ratty = create_track("rat", confidence=0.6)
        hedgehog = create_track("hedgehog", confidence=0.65)
        assert self.get_tags([ratty, hedgehog]) == {
            UNIDENTIFIED: {CONFIDENCE: DEFAULT_CONFIDENCE}
        }

    def test_multi_track_different_ignore_poor_quality(self):
        ratty = create_track("rat")
        hedgehog = create_track("hedgehog", confidence=0.35)
        assert self.get_tags([ratty, hedgehog]) == {
            "rat": {CONFIDENCE: 0.9},
            UNIDENTIFIED: {CONFIDENCE: DEFAULT_CONFIDENCE},
        }

    def test_multi_track_same_animal_and_poor_confidence_gives_one_tags(self):
        ratty1 = create_track("rat")
        ratty2 = create_track("rat", confidence=0.3)
        assert self.get_tags([ratty1, ratty2]) == {
            "rat": {CONFIDENCE: 0.9},
            UNIDENTIFIED: {CONFIDENCE: DEFAULT_CONFIDENCE},
        }

    def test_multi_track_same_animal_one_poor_confidence_good_clarity(self):
        ratty1 = create_track("rat")
        ratty2 = create_track("rat", confidence=0.6, clarity=0.06)

        assert self.get_tags([ratty1, ratty2]) == {
            "rat": {CONFIDENCE: 0.9},
            UNIDENTIFIED: {CONFIDENCE: DEFAULT_CONFIDENCE},
        }

    def test_multi_track_same_animal_but_poor_clarity(self):
        ratty1 = create_track("rat")
        ratty2 = create_track("rat", clarity=0.01)
        assert self.get_tags([ratty1, ratty2]) == {
            "rat": {CONFIDENCE: 0.9},
            UNIDENTIFIED: {CONFIDENCE: DEFAULT_CONFIDENCE},
        }

    def test_multi_track_animal_at_the_same_time_results_in_muliple_tag(self):
        ratty1 = create_track("rat")
        ratty2 = create_track("rat", confidence=0.6)
        ratty1["start_s"] = 5
        ratty1["end_s"] = 8
        ratty2["start_s"] = 3
        ratty2["end_s"] = 7
        assert self.get_tags([ratty1, ratty2])[MULTIPLE] == {
            "event": MULTIPLE,
            CONFIDENCE: 0.6,
        }

    def test_not_first_tracks_overlap(self):
        ratty1 = create_track("rat", confidence=0.9)
        ratty2 = create_track("rat", confidence=0.7)
        ratty1["start_s"] = 1
        ratty1["end_s"] = 8
        ratty2["start_s"] = 5
        ratty2["end_s"] = 8
        assert self.get_tags([ratty1, ratty2])[MULTIPLE] == {
            "event": MULTIPLE,
            CONFIDENCE: 0.7,
        }

    #
    # def test_calc_track_movement(self):
    #     positions = [{"start_s": 1, "x": 2, "y": 24, "width": 42, "height": 44}]
    #     assert calc_track_movement({"positions": positions}) == 0.0
    #     positions.append({"start_s": 2, "x": 40, "y": 14, "width": 48, "height": 54})
    #     assert calc_track_movement({"positions": positions}) == 22.0
    #     positions.append({"start_s": 3, "x": 40, "y": 106, "width": 48, "height": 146})
    #     assert calc_track_movement({"positions": positions}) == 92.0

    def test_large_track_movement_means_actual_track_even_with_low_confidence(self):
        poor_rat = create_track("rat", confidence=0.3)
        poor_rat["positions"] = [
            {"start_s": 1, "x": 2, "y": 24, "width": 42, "height": 44},
            {"start_s": 2, "x": 102, "y": 24, "width": 142, "height": 44},
        ]
        assert self.get_tags([poor_rat]) == {
            UNIDENTIFIED: {CONFIDENCE: DEFAULT_CONFIDENCE}
        }

    def get_tags(self, tracks):
        _, tags = calculate_tags(tracks, self.conf)
        return tags


def create_prediction(
    animal,
    confidence=0.9,
    clarity=0.2,
    novelty=0.5,
    model_name="Test AI",
    model_id=1,
    tag=None,
):
    prediction = {
        "id": model_id,
        "name": model_name,
        LABEL: animal,
        CONFIDENCE: confidence,
        "clarity": clarity,
        "average_novelty": novelty,
    }
    if tag:
        prediction[TAG] = tag
    return prediction


def create_track(
    animal,
    confidence=0.9,
    clarity=0.2,
    novelty=0.5,
    model_name="Test AI",
    model_id=1,
    tag=None,
):
    TestTagCalculations.TIME += 3
    track = {
        "predictions": [
            create_prediction(
                animal, confidence, clarity, novelty, model_name, model_id, tag
            )
        ],
        "num_frames": 18,
        "start_s": TestTagCalculations.TIME,
        "end_s": TestTagCalculations.TIME + 2,
    }
    return track
