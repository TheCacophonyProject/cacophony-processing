from processing import calculate_tag, FALSE_POSITIVE, UNIDENTIFIED

class TestTagCalculations:

    def test_no_tracks(self):
        assert calculate_tag([]) == (FALSE_POSITIVE, 0.8)

    def test_one_track(self):
        assert calculate_tag([{
            'label': 'rat',
            'confidence': 0.9,
        }]) == ('rat', 0.9)

    def test_one_track_low_confidence(self):
        assert calculate_tag([{
            'label': 'rat',
            'confidence': 0.5,
        }]) == (UNIDENTIFIED, 0.8)

    def test_multi_track_same_animal(self):
        assert calculate_tag([
            {'label': 'rat', 'confidence': 0.5},
            {'label': 'rat', 'confidence': 0.9},
        ]) == ('rat', 0.9)

    def test_multi_track_two_animals(self):
        assert calculate_tag([
            {'label': 'rat', 'confidence': 0.9},
            {'label': 'possum', 'confidence': 0.9},
        ]) == (UNIDENTIFIED, 0.8)

    def test_animal_and_false_positive(self):
        assert calculate_tag([
            {'label': 'false-positive', 'confidence': 0.9},
            {'label': 'rat', 'confidence': 0.85},
        ]) == ('rat', 0.85)

    def test_low_confidence_animal_and_false_positive(self):
        assert calculate_tag([
            {'label': 'false-positive', 'confidence': 0.9},
            {'label': 'rat', 'confidence': 0.7},
        ]) == (FALSE_POSITIVE, 0.9)

    def test_many_strong(self):
        assert calculate_tag([
            {'label': 'rat', 'confidence': 0.9},
            {'label': 'possum', 'confidence': 0.9},
            {'label': 'false-positive', 'confidence': 0.9},
        ]) == (UNIDENTIFIED, 0.8)
