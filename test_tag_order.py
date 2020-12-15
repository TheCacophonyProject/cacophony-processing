from processing import config, thermal


def test_models():
    original = config.Model(
        name="original",
        model_file="original.sav",
        tag_scores={"bird": 4, "default": 1},
        preview="none",
        wallaby=False,
        ignored_tags=["mustelid"],
    )
    retrained = config.Model(
        name="retrained",
        model_file="retrained.sav",
        tag_scores={"default": 2},
        preview="none",
        wallaby=False,
        ignored_tags=[],
    )
    resnet = config.Model(
        name="resnet",
        model_file="resnet.sav",
        tag_scores={"default": 3},
        preview="none",
        wallaby=False,
        ignored_tags=[],
    )
    wallaby = config.Model(
        name="wallaby",
        model_file="wallaby.sav",
        tag_scores={"default": 2},
        preview="none",
        wallaby=True,
        ignored_tags=[],
    )
    wallaby_old = config.Model(
        name="wallaby-old",
        model_file="wallaby-old.sav",
        tag_scores={"default": 1},
        preview="none",
        wallaby=True,
        ignored_tags=[],
    )
    return [original, retrained, resnet, wallaby, wallaby_old]


def test_config():
    return config.Config(
        bucket_name="caocphony",
        endpoint_url="http://127.0.0.1:9001",
        access_key="minio",
        secret_key="miniostorage",
        api_url="http://127.0.0.1:2008/api/fileProcessing",
        no_recordings_wait_secs=30,
        classify_dir="",
        classify_cmd="",
        do_classify=True,
        wallaby_devices=[1, 2],
        master_tag="Master",
        models=test_models(),
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
    )


def model_result(model, tag):
    track = {"tag": tag}
    model_result = thermal.ModelResult(
        model_config=model, tracks=[], tags=[], algorithm_id=1
    )
    return (model_result, track)


def test_model_heirechy_wallabies():
    config = test_config()
    original_result = model_result(config.models[0], "wallaby")
    retrained_result = model_result(config.models[1], "wallaby")
    resnet_result = model_result(config.models[2], "wallaby")
    wallaby_result = model_result(config.models[3], None)
    wallaby_old_result = model_result(config.models[4], "wallaby")
    results = [
        original_result,
        retrained_result,
        resnet_result,
        wallaby_result,
        wallaby_old_result,
    ]
    # old wallaby is chosen over no tag
    master_tag = thermal.get_master_tag(results, wallaby_device=True)
    assert master_tag[0].model_config.name == "wallaby-old"
    assert master_tag[1]["tag"] == "wallaby"

    # new wallaby tag is chosen over old
    wallaby_result[1]["tag"] = "wallaby"
    master_tag = thermal.get_master_tag(results, wallaby_device=True)
    assert master_tag[0].model_config.name == "wallaby"
    assert master_tag[1]["tag"] == "wallaby"

    wallaby_result[1]["tag"] = "bird"
    wallaby_old_result[1]["tag"] = "possum"

    # no wallaby tags, means no tag
    master_tag = thermal.get_master_tag(results, wallaby_device=True)
    assert master_tag is None


def test_model_heirechy():
    config = test_config()
    original_result = model_result(config.models[0], "bird")
    retrained_result = model_result(config.models[1], "cat")
    resnet_result = model_result(config.models[2], "possum")
    wallaby_result = model_result(config.models[3], "not")
    wallaby_old_result = model_result(config.models[4], "not")
    results = [
        original_result,
        retrained_result,
        resnet_result,
        wallaby_result,
        wallaby_old_result,
    ]

    # original bird classification overrules all others
    master_tag = thermal.get_master_tag(results, wallaby_device=False)
    assert master_tag[0].model_config.name == "original"
    assert master_tag[1]["tag"] == "bird"

    # if the original model isn't a bird, resnet is the next best
    original_result[1]["tag"] = "cat"
    master_tag = thermal.get_master_tag(results, wallaby_device=False)
    assert master_tag[0].model_config.name == "resnet"
    assert master_tag[1]["tag"] == "possum"

    # if resent doens't know, use retrained
    resnet_result[1]["tag"] = None
    master_tag = thermal.get_master_tag(results, wallaby_device=False)
    assert master_tag[0].model_config.name == "retrained"
    assert master_tag[1]["tag"] == "cat"

    # if resent is unidentified use retrained
    resnet_result[1]["tag"] = "unidentified"
    master_tag = thermal.get_master_tag(results, wallaby_device=False)
    assert master_tag[0].model_config.name == "retrained"
    assert master_tag[1]["tag"] == "cat"

    # if all models are unidentified use unidentified
    retrained_result[1]["tag"] = "unidentified"
    original_result[1]["tag"] = "unidentified"
    master_tag = thermal.get_master_tag(results, wallaby_device=False)
    assert master_tag[1]["tag"] == "unidentified"

    # if none make a tag then no tag is used
    retrained_result[1]["tag"] = None
    original_result[1]["tag"] = None
    resnet_result[1]["tag"] = None
    master_tag = thermal.get_master_tag(results, wallaby_device=False)
    assert master_tag is None

    original_result[1]["tag"] = "unidentified"
    master_tag = thermal.get_master_tag(results, wallaby_device=False)
    assert master_tag[1]["tag"] == "unidentified"

    # original model should ignore mustelid
    original_result[1]["tag"] = "mustelid"
    master_tag = thermal.get_master_tag(results, wallaby_device=False)
    assert master_tag is None

    original_result[1]["tag"] = "cat"
    master_tag = thermal.get_master_tag(results, wallaby_device=False)
    assert master_tag[1]["tag"] == "cat"
