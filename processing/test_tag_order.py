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
        restart_after=None,
        temp_dir="/",
        api_credentials=config.APICredentials(
            api_url="http://127.0.0.1:2008/api/fileProcessing",
            user="test",
            password="testpass",
        ),
        no_recordings_wait_secs=30,
        classify_image="",
        classify_cmd="",
        track_cmd="",
        wallaby_devices=[1, 2],
        master_tag="Master",
        min_confidence=0.4,
        min_tag_confidence=0.8,
        max_tag_novelty=0.7,
        min_tag_clarity=0.2,
        min_tag_clarity_secondary=0.05,
        audio_analysis_cmd="",
        audio_analysis_tag="v1.1.0",
        audio_analysis_workers=1,
        thermal_analyse_workers=1,
        ignore_tags=["not"],
        cache_clips_bigger_than=0,
        thermal_tracking_workers=1,
        trail_workers=1,
        classify_trail_cmd="",
        do_retrack=False,
        ir_tracking_workers=0,
        ir_analyse_workers=0,
        filter_false_positive=True,
        false_positive_min_confidence=0.7,
        max_tracks=10,
        no_job_sleep_seconds=30,
        subprocess_timeout=1200,
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
    models_by_id = {}
    for mod in models:
        models_by_id[mod.id] = mod
    original_result = create_prediction("wallaby", tag="wallaby", model_id=models[0].id)

    retrained_result = create_prediction(
        "wallaby", tag="wallaby", model_id=models[1].id
    )

    resnet_result = create_prediction("wallaby", tag="wallaby", model_id=models[2].id)

    wallaby_result = create_prediction("wallaby", model_id=models[3].id)

    wallaby_old_result = create_prediction(
        "wallaby", tag="wallaby", model_id=models[4].id
    )

    results = [
        original_result,
        retrained_result,
        resnet_result,
        wallaby_result,
        wallaby_old_result,
    ]
    print("Id is ", models_by_id)
    print(results)
    # old wallaby is chosen over no tag
    master_model, master_prediction = thermal.get_master_tag(
        results, models_by_id, wallaby_device=True
    )
    assert master_model.name == "wallaby-old"
    assert master_prediction.tag == "wallaby"

    # new wallaby tag is chosen over old
    wallaby_result.tag = "wallaby"
    master_model, master_prediction = thermal.get_master_tag(
        results, models_by_id, wallaby_device=True
    )
    assert master_model.name == "wallaby"
    assert master_prediction.tag == "wallaby"

    wallaby_result.tag = "bird"
    wallaby_old_result.tag = "possum"

    master_model, master_prediction = thermal.get_master_tag(
        results, models_by_id, wallaby_device=True
    )
    assert master_model.name == "resnet"
    assert master_prediction.tag == "wallaby"


def test_model_heirechy():
    config = test_config()
    models = test_models()
    models_by_id = {}
    for mod in models:
        models_by_id[mod.id] = mod
    original_result = create_prediction("bird", tag="bird", model_id=models[0].id)
    retrained_result = create_prediction("cat", tag="cat", model_id=models[1].id)
    resnet_result = create_prediction("possum", tag="possum", model_id=models[2].id)
    wallaby_result = create_prediction("not", tag="not", model_id=models[3].id)
    wallaby_old_result = create_prediction("not", tag="not", model_id=models[4].id)
    results = [
        original_result,
        retrained_result,
        resnet_result,
        wallaby_result,
        wallaby_old_result,
    ]

    # original bird classification overrules all others
    master_model, master_prediction = thermal.get_master_tag(
        results, models_by_id, wallaby_device=False
    )
    assert master_model.name == "original"
    assert master_prediction.tag == "bird"

    # if the original model isn't a bird, resnet is the next best
    original_result.tag = "cat"
    master_model, master_prediction = thermal.get_master_tag(
        results, models_by_id, wallaby_device=False
    )
    assert master_model.name == "resnet"
    assert master_prediction.tag == "possum"

    # if resent doens't know, use retrained
    resnet_result.tag = None
    master_model, master_prediction = thermal.get_master_tag(
        results, models_by_id, wallaby_device=False
    )
    assert master_model.name == "retrained"
    assert master_prediction.tag == "cat"

    # if resent is unidentified use retrained
    resnet_result.tag = "unidentified"
    master_model, master_prediction = thermal.get_master_tag(
        results, models_by_id, wallaby_device=False
    )
    assert master_model.name == "retrained"
    assert master_prediction.tag == "cat"

    # if all models are unidentified use unidentified
    retrained_result.tag = "unidentified"
    original_result.tag = "unidentified"
    master_model, master_prediction = thermal.get_master_tag(
        results, models_by_id, wallaby_device=False
    )
    assert master_prediction.tag == "unidentified"

    # if none make a tag then no tag is used
    retrained_result.tag = None
    original_result.tag = None
    resnet_result.tag = None
    master_model, master_prediction = thermal.get_master_tag(
        results, models_by_id, wallaby_device=False
    )
    assert master_prediction is None

    original_result.tag = "unidentified"
    master_model, master_prediction = thermal.get_master_tag(
        results, models_by_id, wallaby_device=False
    )
    assert master_prediction.tag == "unidentified"

    # original model should ignore mustelid
    original_result.tag = "mustelid"
    master_model, master_prediction = thermal.get_master_tag(
        results, models_by_id, wallaby_device=False
    )
    assert master_prediction is None

    original_result.tag = "cat"
    master_model, master_prediction = thermal.get_master_tag(
        results, models_by_id, wallaby_device=False
    )
    assert master_prediction.tag == "cat"
