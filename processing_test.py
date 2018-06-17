"""
cacophony-processing - this is a server side component that runs alongside
the Cacophony Project API, performing post-upload processing tasks.
Copyright (C) 2018, The Cacophony Project

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program. If not, see <http://www.gnu.org/licenses/>.
"""


from processing import calculate_tag, FALSE_POSITIVE, UNIDENTIFIED

class TestTagCalculations:

    def test_no_tracks(self):
        assert calculate_tag([]) == (FALSE_POSITIVE, 0.85)

    def test_one_track(self):
        assert calculate_tag([{
            'label': 'rat',
            'confidence': 0.9,
        }]) == ('rat', 0.9)

    def test_one_track_low_confidence(self):
        assert calculate_tag([{
            'label': 'rat',
            'confidence': 0.5,
        }]) == (UNIDENTIFIED, 0.85)

    def test_false_positive_low_confidence(self):
        assert calculate_tag([
            {'label': 'false-positive', 'confidence': 0.39},
        ]) == (FALSE_POSITIVE, 0.85)

    def test_multi_false_positive(self):
        assert calculate_tag([
            {'label': 'false-positive', 'confidence': 0.39},
            {'label': 'false-positive', 'confidence': 0.50},
            {'label': 'false-positive', 'confidence': 0.12},
        ]) == (FALSE_POSITIVE, 0.85)

    def test_multi_track_same_animal(self):
        assert calculate_tag([
            {'label': 'rat', 'confidence': 0.5},
            {'label': 'rat', 'confidence': 0.9},
        ]) == ('rat', 0.9)

    def test_multi_track_two_animals(self):
        assert calculate_tag([
            {'label': 'rat', 'confidence': 0.9},
            {'label': 'possum', 'confidence': 0.9},
        ]) == (UNIDENTIFIED, 0.85)

    def test_animal_and_false_positive(self):
        assert calculate_tag([
            {'label': 'false-positive', 'confidence': 0.9},
            {'label': 'rat', 'confidence': 0.88},
        ]) == ('rat', 0.88)

    def test_low_confidence_animal_and_false_positive(self):
        assert calculate_tag([
            {'label': 'false-positive', 'confidence': 0.46},
            {'label': 'rat', 'confidence': 0.7},
        ]) == (UNIDENTIFIED, 0.85)

    def test_many_strong(self):
        assert calculate_tag([
            {'label': 'rat', 'confidence': 0.9},
            {'label': 'possum', 'confidence': 0.9},
            {'label': 'false-positive', 'confidence': 0.9},
        ]) == (UNIDENTIFIED, 0.85)
