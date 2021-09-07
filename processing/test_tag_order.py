from processing import config, thermal
from processing.tagger_test import create_prediction


def test_models():
    original = config.ModelConfig(
        id="1",
        name="original",
        model_file="original.sav",
        tag_scores={"bird": 4, "default": 1},
        wallaby=False,
        ignored_tags=["mustelid"],
        classify_time=0,
    )
    retrained = config.ModelConfig(
        id="2",
        name="retrained",
        model_file="retrained.sav",
        tag_scores={"default": 2},
        wallaby=False,
        ignored_tags=[],
        classify_time=0,
    )
    resnet = config.ModelConfig(
        id="3",
        name="resnet",
        model_file="resnet.sav",
        tag_scores={"default": 3},
        wallaby=False,
        ignored_tags=[],
        classify_time=0,
    )
    wallaby = config.ModelConfig(
        id="4",
        name="wallaby",
        model_file="wallaby.sav",
        tag_scores={"default": 2, "wallaby": 6},
        wallaby=True,
        ignored_tags=[],
        classify_time=0,
    )
    wallaby_old = config.ModelConfig(
        id="5",
        name="wallaby-old",
        model_file="wallaby-old.sav",
        tag_scores={"default": 1, "wallaby": 5},
        wallaby=True,
        ignored_tags=[],
        classify_time=0,
    )
    return [original, retrained, resnet, wallaby, wallaby_old]


def test_config():
    return config.Config(
        file_api_url="http://127.0.0.1:2008/api/fileProcessing",
        api_url="http://127.0.0.1:2008/api/fileProcessing",
        no_recordings_wait_secs=30,
        classify_dir="",
        classify_cmd="",
        do_classify=True,
        wallaby_devices=[1, 2],
        master_tag="Master",
        min_confidence=0.4,
        min_tag_confidence=0.8,
        max_tag_novelty=0.7,
        min_tag_clarity=0.2,
        min_tag_clarity_secondary=0.05,
        min_frames=3,
        animal_movement=50,
        audio_analysis_cmd="",
        audio_analysis_tag="v1.1.0",
        audio_convert_workers=1,
        audio_analysis_workers=1,
        thermal_workers=1,
        ignore_tags=["not"],
        cache_clips_bigger_than=0,
    )


def model_result(model, tag):
    track = {"tag": tag}
    model_result = thermal.ModelResult(
        model_config=model, tracks=[], tags=[], algorithm_id=1
    )
    return (model_result, track)


def test_model_heirechy_wallabies():
    config = test_config()
    models = test_models()
    original_result = (
        models[0],
        create_prediction("wallaby", tag="wallaby"),
    )
    retrained_result = (
        models[1],
        create_prediction("wallaby", tag="wallaby"),
    )
    resnet_result = (
        models[2],
        create_prediction("wallaby", tag="wallaby"),
    )
    wallaby_result = (
        models[3],
        create_prediction("wallaby"),
    )
    wallaby_old_result = (
        models[4],
        create_prediction("wallaby", tag="wallaby"),
    )
    results = [
        original_result,
        retrained_result,
        resnet_result,
        wallaby_result,
        wallaby_old_result,
    ]
    # old wallaby is chosen over no tag
    master_model, master_prediction = thermal.get_master_tag(
        results, wallaby_device=True
    )
    assert master_model.name == "wallaby-old"
    assert master_prediction["tag"] == "wallaby"

    # new wallaby tag is chosen over old
    wallaby_result[1]["tag"] = "wallaby"
    master_model, master_prediction = thermal.get_master_tag(
        results, wallaby_device=True
    )
    assert master_model.name == "wallaby"
    assert master_prediction["tag"] == "wallaby"

    wallaby_result[1]["tag"] = "bird"
    wallaby_old_result[1]["tag"] = "possum"

    master_model, master_prediction = thermal.get_master_tag(
        results, wallaby_device=True
    )
    assert master_model.name == "resnet"
    assert master_prediction["tag"] == "wallaby"


def test_model_heirechy():
    config = test_config()
    models = test_models()

    original_result = (
        models[0],
        create_prediction("bird", tag="bird"),
    )
    retrained_result = (
        models[1],
        create_prediction("cat", tag="cat"),
    )
    resnet_result = (
        models[2],
        create_prediction("possum", tag="possum"),
    )
    wallaby_result = (
        models[3],
        create_prediction("not", tag="not"),
    )
    wallaby_old_result = (
        models[4],
        create_prediction("not", tag="not"),
    )
    results = [
        original_result,
        retrained_result,
        resnet_result,
        wallaby_result,
        wallaby_old_result,
    ]

    # original bird classification overrules all others
    master_model, master_prediction = thermal.get_master_tag(
        results, wallaby_device=False
    )
    assert master_model.name == "original"
    assert master_prediction["tag"] == "bird"

    # if the original model isn't a bird, resnet is the next best
    original_result[1]["tag"] = "cat"
    master_model, master_prediction = thermal.get_master_tag(
        results, wallaby_device=False
    )
    assert master_model.name == "resnet"
    assert master_prediction["tag"] == "possum"

    # if resent doens't know, use retrained
    resnet_result[1]["tag"] = None
    master_model, master_prediction = thermal.get_master_tag(
        results, wallaby_device=False
    )
    assert master_model.name == "retrained"
    assert master_prediction["tag"] == "cat"

    # if resent is unidentified use retrained
    resnet_result[1]["tag"] = "unidentified"
    master_model, master_prediction = thermal.get_master_tag(
        results, wallaby_device=False
    )
    assert master_model.name == "retrained"
    assert master_prediction["tag"] == "cat"

    # if all models are unidentified use unidentified
    retrained_result[1]["tag"] = "unidentified"
    original_result[1]["tag"] = "unidentified"
    master_model, master_prediction = thermal.get_master_tag(
        results, wallaby_device=False
    )
    assert master_prediction["tag"] == "unidentified"

    # if none make a tag then no tag is used
    retrained_result[1]["tag"] = None
    original_result[1]["tag"] = None
    resnet_result[1]["tag"] = None
    master_model, master_prediction = thermal.get_master_tag(
        results, wallaby_device=False
    )
    assert master_prediction is None

    original_result[1]["tag"] = "unidentified"
    master_model, master_prediction = thermal.get_master_tag(
        results, wallaby_device=False
    )
    assert master_prediction["tag"] == "unidentified"

    # original model should ignore mustelid
    original_result[1]["tag"] = "mustelid"
    master_model, master_prediction = thermal.get_master_tag(
        results, wallaby_device=False
    )
    assert master_prediction is None

    original_result[1]["tag"] = "cat"
    master_model, master_prediction = thermal.get_master_tag(
        results, wallaby_device=False
    )
    assert master_prediction["tag"] == "cat"
