from operator import itemgetter
from itertools import groupby

MIN_TRACK_CONFIDENCE = 0.85
FALSE_POSITIVE = "false-positive"
UNIDENTIFIED = "unidentified"
MULTIPLE = "multiple animals"
STATUS = "status"

MESSAGE = 'message'
CONFIDENCE = 'confidence'

def calculate_tags(tracks, conf):
  # No tracks found so tag as FALSE_POSITIVE
  tags = {}
  if not tracks:
    tags[FALSE_POSITIVE] = {"event": FALSE_POSITIVE, CONFIDENCE: MIN_TRACK_CONFIDENCE}
    return tags

  toBeTagged, unknowns = findSignificantTracks(tracks, conf)

  if len(unknowns) > 0:
    tags[UNIDENTIFIED] = {CONFIDENCE: MIN_TRACK_CONFIDENCE}

  sortedTags = sorted(toBeTagged, key=itemgetter("label"))
  for label, label_tracks in groupby(toBeTagged, itemgetter("label")):
    confidence = max(t[CONFIDENCE] for t in label_tracks)
    tags[label] = {CONFIDENCE: confidence}

  if len(tags) == 0:
    tags[FALSE_POSITIVE] = {"event": FALSE_POSITIVE, CONFIDENCE: MIN_TRACK_CONFIDENCE}
  else:
    multipleConfidence = multipleAnimalConfidence(toBeTagged, unknowns)
    if multipleConfidence > conf.min_confidence:
      tags[MULTIPLE] = {"event": MULTIPLE, CONFIDENCE: multipleConfidence}

  print(tags)
  return tags


def findSignificantTracks(tracks, conf):
  toBeTagged = []
  unknowns = []

  for track in tracks:
    if track['confidence'] < conf.min_confidence:
      track[MESSAGE] = "Very low confidence - ignore"
    elif track["label"] == FALSE_POSITIVE and track["clarity"] > conf.min_tag_clarity / 2:
      continue
    else:
      if track[CONFIDENCE] < conf.min_tag_confidence:
        track[MESSAGE] = "Low confidence - no tag"
      elif track["clarity"] < conf.min_tag_clarity:
        track[MESSAGE] = "Confusion between two classes (similar confidence)"
      elif track["average_novelty"] > conf.max_tag_novelty:
        track[MESSAGE] = "High novelty"
      else:
        toBeTagged.append(track)
        track[STATUS] = 'tag'
        continue

      if track["num_frames"] < conf.min_frames:
        # Ignore min_frames if we are sure we know what it is else throw it away
        track[MESSAGE] = "Short track"
      else:
        unknowns.append(track)
        track[STATUS] = 'unknown'
  return (toBeTagged, unknowns)

def byStartTime(elem):
    return elem["start_s"]

def multipleAnimalConfidence(animals, possibles):
  confidence = 0

  animalTracks = animals + possibles
  animalTracks.sort(key=byStartTime)
  print (animalTracks)
  for i in range(0, len(animalTracks) - 1):
    for j in range(i+1, len(animalTracks)):
      if animalTracks[j]["start_s"] < animalTracks[i]["end_s"]:
        thisMatchConf = min(animalTracks[i][CONFIDENCE], animalTracks[j][CONFIDENCE])
        confidence = max(confidence, thisMatchConf)
  print("Confidence")
  print(confidence)
  return confidence

