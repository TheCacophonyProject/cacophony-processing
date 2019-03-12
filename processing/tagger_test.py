from processing.tagger import calc_track_movement, calculate_tags, MULTIPLE, FALSE_POSITIVE, UNIDENTIFIED, MESSAGE, CONFIDENCE
import json
import processing

class TestTagCalculations:
    conf = processing.Config
    conf.min_confidence = .4
    conf.min_tag_confidence = .8
    conf.max_tag_novelty = .6
    conf.min_tag_clarity = .1
    conf.min_tag_clarity_secondary = .05
    conf.min_frames = 4
    time = -2

    def test_no_tracks(self):
        assert self.get_tags([]) == {}

    def test_one_false_positive_track(self):
        falsy = self.create_good_track(FALSE_POSITIVE)
        assert self.get_tags([falsy]) == false_positive_result()

    def test_one_track(self):
        goodRatty = self.create_good_track("rat")
        assert self.get_tags([goodRatty]) == {"rat": {CONFIDENCE: 0.9}}

    def test_ignores_short_not_great_track(self):
        shortRatty = self.create_good_track("rat")
        shortRatty["num_frames"] = 2
        shortRatty[CONFIDENCE] = .65
        assert self.get_tags([shortRatty]) == false_positive_result()

    def test_one_track_middle_confidence(self):
        rat = self.create_good_track("rat")
        rat[CONFIDENCE] = 0.6
        assert self.get_tags([rat]) == {UNIDENTIFIED: {CONFIDENCE: 0.85}}
        assert rat[MESSAGE] == "Low confidence - no tag"

    def test_only_ever_one_unidentified_tag(self):
        rat1 = self.create_good_track("rat")
        rat1[CONFIDENCE] = 0.6
        rat2 = self.create_good_track("rat")
        rat2[CONFIDENCE] = 0.6
        assert self.get_tags([rat1, rat2]) == {UNIDENTIFIED: {CONFIDENCE: 0.85}}

    def test_one_track_poor_confidence(self):
        poorRatty = self.create_good_track("rat")
        poorRatty[CONFIDENCE] = 0.3
        assert self.get_tags([poorRatty]) == false_positive_result()
        assert poorRatty[MESSAGE] == "Low movement and poor confidence - ignore"

    def test_one_track_poor_clarity_gives_unidentified(self):
        poorRatty = self.create_good_track("rat")
        poorRatty["clarity"] = 0.02
        assert self.get_tags([poorRatty]) == {UNIDENTIFIED: {CONFIDENCE: 0.85}}
        assert poorRatty[MESSAGE] == "Confusion between two classes (similar confidence)"

    def test_one_track_high_novelty_gives_unidentified(self):
        poorRatty = self.create_good_track("rat")
        poorRatty["average_novelty"] = 0.88
        assert self.get_tags([poorRatty]) == {UNIDENTIFIED: {CONFIDENCE: 0.85}}
        assert poorRatty[MESSAGE] == "High novelty"

    def test_multi_track_same_animal_gives_only_one_tag(self):
        ratty1 = self.create_good_track("rat")
        ratty2 = self.create_good_track("rat")
        ratty2[CONFIDENCE] = 0.95
        assert self.get_tags([ratty1, ratty2]) == {"rat": {CONFIDENCE: 0.95}}

    def test_multi_track_different_animal_tags_both(self):
        ratty = self.create_good_track("rat")
        hedgehog = self.create_good_track("hedgehog")
        hedgehog[CONFIDENCE] = 0.95
        assert self.get_tags([ratty, hedgehog]) == {"rat": {CONFIDENCE: 0.9}, "hedgehog": {CONFIDENCE: 0.95}}

    def test_multi_track_different_animal_poor_middle_confidence_tags_unidentified(self):
        ratty = self.create_good_track("rat")
        ratty[CONFIDENCE] = 0.6
        hedgehog = self.create_good_track("hedgehog")
        hedgehog[CONFIDENCE] = 0.65
        assert self.get_tags([ratty, hedgehog]) == {UNIDENTIFIED: {CONFIDENCE: 0.85}}

    def test_multi_track_different_ignore_poor_quality(self):
        ratty = self.create_good_track("rat")
        hedgehog = self.create_good_track("hedgehog")
        hedgehog[CONFIDENCE] = 0.35
        assert self.get_tags([ratty, hedgehog]) == {"rat": {CONFIDENCE: 0.9}}

    def test_multi_track_same_animal_and_poor_confidence_gives_one_tags(self):
        ratty1 = self.create_good_track("rat")
        ratty2 = self.create_good_track("rat")
        ratty2[CONFIDENCE] = 0.3
        assert self.get_tags([ratty1, ratty2]) == {"rat": {CONFIDENCE: 0.9}}

    def test_multi_track_same_animal_one_poor_confidence_good_clarity(self):
        ratty1 = self.create_good_track("rat")
        ratty2 = self.create_good_track("rat")
        ratty2[CONFIDENCE] = 0.6
        ratty2["clarity"] = 0.06
        assert self.get_tags([ratty1, ratty2]) == {"rat": {CONFIDENCE: 0.9}}

    def test_multi_track_same_animal_but_poor_clarity(self):
        ratty1 = self.create_good_track("rat")
        ratty2 = self.create_good_track("rat")
        ratty2["clarity"] = 0.01
        assert self.get_tags([ratty1, ratty2]) == {"rat": {CONFIDENCE: 0.9}, UNIDENTIFIED: {CONFIDENCE: 0.85}}

    def test_multi_track_ignores_false_positives_if_animal(self):
        ratty1 = self.create_good_track("rat")
        ratty1[CONFIDENCE] = 0.6
        falsy = self.create_good_track(FALSE_POSITIVE)
        assert self.get_tags([ratty1, falsy]) == {UNIDENTIFIED: {CONFIDENCE: 0.85}}

    def test_multi_track_animal_at_the_same_time_results_in_muliple_tag(self):
        ratty1 = self.create_good_track("rat")
        ratty2 = self.create_good_track("rat")
        ratty1["start_s"] = 5
        ratty1["end_s"] = 8
        ratty2["start_s"] = 3
        ratty2["end_s"] = 7
        ratty2[CONFIDENCE] = .6
        assert self.get_tags([ratty1, ratty2])[MULTIPLE] == {'event': MULTIPLE, CONFIDENCE: 0.6}

    def test_not_first_tracks_overlap(self):
        ratty1 = self.create_good_track("rat")
        ratty2 = self.create_good_track("rat")
        ratty3 = self.create_good_track("rat")
        ratty1["start_s"] = 1
        ratty1["end_s"] = 8
        ratty1[CONFIDENCE] = .9
        ratty2["start_s"] = 5
        ratty2["end_s"] = 8
        ratty2[CONFIDENCE] = .6
        ratty3["start_s"] = 7
        ratty3["end_s"] = 11
        ratty2[CONFIDENCE] = .7
        assert self.get_tags([ratty1, ratty2])[MULTIPLE] == {'event': MULTIPLE, CONFIDENCE: 0.7}

    def test_calc_track_movement(self):
        positions = [(1, (2, 24, 42, 44))]
        assert calc_track_movement({"positions": positions}) == 0.0
        positions.append((2, (40, 14, 48, 54)))
        assert calc_track_movement({"positions": positions}) == 22.0
        positions.append((3, (40, 106, 48, 146)))
        assert calc_track_movement({"positions": positions}) == 92.0

    def test_large_track_movement_means_actual_track_even_with_low_confidence(self):
        poor_rat = self.create_good_track("rat")
        poor_rat[CONFIDENCE] = .3
        poor_rat["positions"] = [(1, (2, 24, 42, 44)), (2, (102, 24, 142, 44))]
        assert self.get_tags([poor_rat]) == {UNIDENTIFIED: {CONFIDENCE: 0.85}}

    def get_tags(self, tracks):
        _, tags = calculate_tags(tracks, self.conf)
        return tags

    def create_good_track(self, animal):
        self.time += 3
        return {"label": animal,
                CONFIDENCE: 0.9,
                "clarity": 0.2,
                "average_novelty": 0.5,
                "num_frames": 18,
                "start_s": self.time,
                "end_s": self.time + 2}

def false_positive_result():
    return {FALSE_POSITIVE: {"event": "false positive", CONFIDENCE: 0.85}}