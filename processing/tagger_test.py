from processing.tagger import findSignificantTracks, calculate_tags, MULTIPLE, FALSE_POSITIVE, UNIDENTIFIED, MESSAGE, CONFIDENCE
import json
import processing

class TestTagCalculations:
  conf = processing.Config
  conf.min_confidence = .4
  conf.min_tag_confidence = .8
  conf.max_tag_novelty = .6
  conf.min_tag_clarity = .1
  conf.min_frames = 4
  time = -2

  def test_no_tracks(self):
    assert self.getTags([]) == falsePositiveResult()

  def test_one_false_positive_track(self):
    falsy = self.createGoodTrack(FALSE_POSITIVE)
    assert self.getTags([falsy]) == falsePositiveResult()

  def test_one_track(self):
    goodRatty = self.createGoodTrack("rat")
    assert self.getTags([goodRatty]) == {"rat": {CONFIDENCE: 0.9}}

  def test_ignores_short_not_great_track(self):
    shortRatty = self.createGoodTrack("rat")
    shortRatty["num_frames"] = 2
    shortRatty[CONFIDENCE] = .65
    assert self.getTags([shortRatty]) == falsePositiveResult()

  def test_one_track_middle_confidence(self):
    rat = self.createGoodTrack("rat")
    rat[CONFIDENCE] = 0.6
    assert self.getTags([rat]) == {UNIDENTIFIED: {CONFIDENCE: 0.85}}
    assert rat[MESSAGE] == "Low confidence - no tag"

  def test_one_track_poor_confidence(self):
    poorRatty = self.createGoodTrack("rat")
    poorRatty[CONFIDENCE] = 0.3
    assert self.getTags([poorRatty]) == falsePositiveResult()
    assert poorRatty[MESSAGE] == "Very low confidence - ignore"

  def test_one_track_poor_clarity_gives_unidentified(self):
    poorRatty = self.createGoodTrack("rat")
    poorRatty["clarity"] = 0.02
    assert self.getTags([poorRatty]) == {UNIDENTIFIED: {CONFIDENCE: 0.85}}
    assert poorRatty[MESSAGE] == "Confusion between two classes (similar confidence)"

  def test_one_track_high_novelty_gives_unidentified(self):
    poorRatty = self.createGoodTrack("rat")
    poorRatty["average_novelty"] = 0.88
    assert self.getTags([poorRatty]) == {UNIDENTIFIED: {CONFIDENCE: 0.85}}
    assert poorRatty[MESSAGE] == "High novelty"

  def test_multi_track_same_animal_gives_only_one_tag(self):
    ratty1 = self.createGoodTrack("rat")
    ratty2 = self.createGoodTrack("rat")
    ratty2[CONFIDENCE] = 0.95
    assert self.getTags([ratty1, ratty2]) == {"rat": {CONFIDENCE: 0.95}}

  def test_multi_track_different_animal_tags_both(self):
    ratty = self.createGoodTrack("rat")
    hedgehog = self.createGoodTrack("hedgehog")
    hedgehog[CONFIDENCE] = 0.95
    assert self.getTags([ratty, hedgehog]) == {"rat": {CONFIDENCE: 0.9}, "hedgehog": {CONFIDENCE: 0.95}}

  def test_multi_track_different_animal_poor_middle_confidence_tags_unidentified(self):
    ratty = self.createGoodTrack("rat")
    ratty[CONFIDENCE] = 0.6
    hedgehog = self.createGoodTrack("hedgehog")
    hedgehog[CONFIDENCE] = 0.65
    assert self.getTags([ratty, hedgehog]) == {UNIDENTIFIED: {CONFIDENCE: 0.85}}

  def test_multi_track_different_ignore_poor_quality(self):
    ratty = self.createGoodTrack("rat")
    hedgehog = self.createGoodTrack("hedgehog")
    hedgehog[CONFIDENCE] = 0.35
    assert self.getTags([ratty, hedgehog]) == {"rat": {CONFIDENCE: 0.9}}

  def test_multi_track_same_animal_and_poor_confidence_gives_one_tags(self):
    ratty1 = self.createGoodTrack("rat")
    ratty2 = self.createGoodTrack("rat")
    ratty2[CONFIDENCE] = 0.3
    assert self.getTags([ratty1, ratty2]) == {"rat": {CONFIDENCE: 0.9}}

  def test_multi_track_same_animal_one_poor_confidence_good_clarity(self):
    ratty1 = self.createGoodTrack("rat")
    ratty2 = self.createGoodTrack("rat")
    ratty2[CONFIDENCE] = 0.6
    ratty2["clarity"] = 0.06
    assert self.getTags([ratty1, ratty2]) == {"rat": {CONFIDENCE: 0.9}}

  def test_multi_track_same_animal_but_poor_clarity(self):
    ratty1 = self.createGoodTrack("rat")
    ratty2 = self.createGoodTrack("rat")
    ratty2["clarity"] = 0.01
    assert self.getTags([ratty1, ratty2]) == {"rat": {CONFIDENCE: 0.9}, UNIDENTIFIED: {CONFIDENCE: 0.85}}

  def test_multi_track_ignores_false_positives_if_animal(self):
    ratty1 = self.createGoodTrack("rat")
    ratty1[CONFIDENCE] = 0.6
    falsy = self.createGoodTrack(FALSE_POSITIVE)
    assert self.getTags([ratty1, falsy]) == {UNIDENTIFIED: {CONFIDENCE: 0.85}}

  def test_multi_track_animal_at_the_same_time_results_in_muliple_tag(self):
    ratty1 = self.createGoodTrack("rat")
    ratty2 = self.createGoodTrack("rat")
    ratty1["start_s"] = 5
    ratty1["end_s"] = 8
    ratty2["start_s"] = 3
    ratty2["end_s"] = 7
    ratty2[CONFIDENCE] = .6
    assert self.getTags([ratty1, ratty2])[MULTIPLE] == {'event': MULTIPLE, CONFIDENCE: 0.6}


  def test_multi_track_animal_at_the_same_time_results_in_muliple_tag(self):
    ratty1 = self.createGoodTrack("rat")
    ratty2 = self.createGoodTrack("rat")
    ratty1["start_s"] = 5
    ratty1["end_s"] = 8
    ratty2["start_s"] = 3
    ratty2["end_s"] = 7
    ratty2[CONFIDENCE] = .6
    assert self.getTags([ratty1, ratty2])[MULTIPLE] == {'event': MULTIPLE, CONFIDENCE: 0.6}

  def test_multi_track_animal_at_the_same_time_results_in_muliple_tag(self):
    ratty1 = self.createGoodTrack("rat")
    ratty2 = self.createGoodTrack("rat")
    ratty1["start_s"] = 5
    ratty1["end_s"] = 8
    ratty2["start_s"] = 3
    ratty2["end_s"] = 7
    ratty2[CONFIDENCE] = .6
    assert self.getTags([ratty1, ratty2])[MULTIPLE] == {'event': MULTIPLE, CONFIDENCE: 0.6}

  def test_not_first_tracks_overlap(self):
    ratty1 = self.createGoodTrack("rat")
    ratty2 = self.createGoodTrack("rat")
    ratty3 = self.createGoodTrack("rat")
    ratty1["start_s"] = 1
    ratty1["end_s"] = 8
    ratty1[CONFIDENCE] = .9
    ratty2["start_s"] = 5
    ratty2["end_s"] = 8
    ratty2[CONFIDENCE] = .6
    ratty3["start_s"] = 7
    ratty3["end_s"] = 11
    ratty2[CONFIDENCE] = .7
    assert self.getTags([ratty1, ratty2])[MULTIPLE] == {'event': MULTIPLE, CONFIDENCE: 0.7}


  # def test_multi_false_positive(self):
  #     assert calculate_tag(
  #         [
  #             {"label": "false-positive", CONFIDENCE: 0.39},
  #             {"label": "false-positive", CONFIDENCE: 0.50},
  #             {"label": "false-positive", CONFIDENCE: 0.12},
  #         ]
  #     ) == (FALSE_POSITIVE, 0.85)




  # def test_format_output(self):
  #     with open('/Users/clare/cacophony/model/runs/20181111-212514.txt') as f:
  #         try:
  #             classify_info = json.loads(f.read())
  #         except json.decoder.JSONDecodeError as err:
  #             raise ValueError(
  #                 "failed to JSON decode classifier output:\n{}".format(f)
  #             ) from err
  #         format_track_data(classify_info['tracks'])

  def getTags(self, tracks):
    return calculate_tags(tracks, self.conf)

  def createGoodTrack(self, animal):
    self.time += 3
    return {"label": animal,
        CONFIDENCE: 0.9,
        "clarity": 0.2,
        "average_novelty": 0.5,
        "num_frames": 18,
        "start_s": self.time,
        "end_s": self.time + 2}

def falsePositiveResult():
  return {FALSE_POSITIVE: {"event": "false positive", CONFIDENCE: 0.85}}