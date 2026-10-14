# Real Ren'Py UI tests: no direct label jump or fabricated romance state.
testsuite global:
    setup:
        skip until screen "main_menu"

testsuite relations:
    before testcase:
        if not screen "main_menu":
            run MainMenu(confirm=False)
        click "开始这一夜"
        advance until screen "night_map"
        assert eval night.tick() == 0
        assert eval len(night.options()) == 4

    after testcase:
        $ renpy.unlink_save("tidelight-test")

    testcase ending_cheng:
        click "看看林遥压在工具箱下的车票"
        advance until screen "choice"
        click "票都买好了。等到了，先告诉我那边食堂怎么样。"
        advance until screen "night_map"
        click "向林遥借一枚备用保险"
        advance until screen "choice"
        click "借给我好吗？今晚我来换，你只在旁边看着。"
        advance until screen "night_map"
        click "听陆弥说起录音上的名字"
        advance until screen "choice"
        click "我想借走，先让许澄决定怎么处理。登记写在哪里？"
        advance until screen "night_map"
        click "把母带带回电台"
        advance until screen "night_map"
        click "翻开最后一册工作簿"
        advance until screen "night_map"
        click "和陆弥看一张暂时失效的船票"
        advance until screen "choice"
        click "那就现在问。等你安顿下来，我能去看看你的工作室吗？"
        advance until screen "night_map"
        click "问许澄，空白后面是什么"
        advance until screen "choice"
        click "不用替所有人决定。今晚，你愿意怎么听、怎么让别人听？"
        advance until screen "night_map"
        click "带备用保险去配电房"
        advance until screen "night_map"
        click "陪许澄听那段突然结束的录音"
        advance until screen "choice"
        click "先别按播放。你想听见后面是什么吗？"
        advance until screen "night_map"
        click "把明天的问题留给许澄回答"
        advance until screen "choice"
        click "不用。明天先一起吃早饭，然后认真商量下一次。"
        advance until screen "night_map"
        assert eval logic.has("BroadcastReady")
        click "留在电台，听一会儿雨"
        advance until screen "night_map"
        click "留在电台，听一会儿雨"
        advance until screen "choice"
        assert eval night.tick() == 12
        click "按大家同意的方式，做完最后一场广播。"
        advance until screen "ending_card"
        assert eval night.ending() == "cheng"

    testcase ending_yao:
        click "看看林遥压在工具箱下的车票"
        advance until screen "choice"
        click "票都买好了。等到了，先告诉我那边食堂怎么样。"
        advance until screen "night_map"
        click "向林遥借一枚备用保险"
        advance until screen "choice"
        click "借给我好吗？今晚我来换，你只在旁边看着。"
        advance until screen "night_map"
        click "听陆弥说起录音上的名字"
        advance until screen "choice"
        click "我想借走，先让许澄决定怎么处理。登记写在哪里？"
        advance until screen "night_map"
        click "把母带带回电台"
        advance until screen "night_map"
        click "翻开最后一册工作簿"
        advance until screen "night_map"
        click "和陆弥看一张暂时失效的船票"
        advance until screen "choice"
        click "那就现在问。等你安顿下来，我能去看看你的工作室吗？"
        advance until screen "night_map"
        click "问许澄，空白后面是什么"
        advance until screen "choice"
        click "不用替所有人决定。今晚，你愿意怎么听、怎么让别人听？"
        advance until screen "night_map"
        click "带备用保险去配电房"
        advance until screen "night_map"
        click "问林遥，抵达之后要不要来信"
        advance until screen "choice"
        click "愿意。也让我把这边无聊的一天寄给你。"
        advance until screen "night_map"
        assert eval logic.has("BroadcastReady")
        assert eval not logic.has("Seen", scene="cheng_pause")
        click "留在电台，听一会儿雨"
        advance until screen "night_map"
        click "留在电台，听一会儿雨"
        advance until screen "night_map"
        click "留在电台，听一会儿雨"
        advance until screen "choice"
        assert eval night.tick() == 12
        click "按大家同意的方式，做完最后一场广播。"
        advance until screen "ending_card"
        assert eval night.ending() == "yao"

    testcase ending_mi:
        click "看看林遥压在工具箱下的车票"
        advance until screen "choice"
        click "票都买好了。等到了，先告诉我那边食堂怎么样。"
        advance until screen "night_map"
        click "向林遥借一枚备用保险"
        advance until screen "choice"
        click "借给我好吗？今晚我来换，你只在旁边看着。"
        advance until screen "night_map"
        click "听陆弥说起录音上的名字"
        advance until screen "choice"
        click "我想借走，先让许澄决定怎么处理。登记写在哪里？"
        advance until screen "night_map"
        click "把母带带回电台"
        advance until screen "night_map"
        click "翻开最后一册工作簿"
        advance until screen "night_map"
        click "和陆弥看一张暂时失效的船票"
        advance until screen "choice"
        click "那就现在问。等你安顿下来，我能去看看你的工作室吗？"
        advance until screen "night_map"
        click "问许澄，空白后面是什么"
        advance until screen "choice"
        click "不用替所有人决定。今晚，你愿意怎么听、怎么让别人听？"
        advance until screen "night_map"
        click "带备用保险去配电房"
        advance until screen "night_map"
        click "与陆弥约一次没有主题的见面"
        advance until screen "choice"
        click "想。我们约一次不用带录音笔的见面。"
        advance until screen "night_map"
        assert eval logic.has("BroadcastReady")
        assert eval not logic.has("Seen", scene="cheng_pause")
        click "留在电台，听一会儿雨"
        advance until screen "night_map"
        click "留在电台，听一会儿雨"
        advance until screen "night_map"
        click "留在电台，听一会儿雨"
        advance until screen "choice"
        assert eval night.tick() == 12
        click "把声音留给愿意坐在这里的人。"
        advance until screen "ending_card"
        assert eval night.ending() == "mi"

    testcase ending_harbor:
        click "看看林遥压在工具箱下的车票"
        advance until screen "choice"
        click "票都买好了。等到了，先告诉我那边食堂怎么样。"
        advance until screen "night_map"
        click "向林遥借一枚备用保险"
        advance until screen "choice"
        click "借给我好吗？今晚我来换，你只在旁边看着。"
        advance until screen "night_map"
        click "听陆弥说起录音上的名字"
        advance until screen "choice"
        click "我想借走，先让许澄决定怎么处理。登记写在哪里？"
        advance until screen "night_map"
        click "把母带带回电台"
        advance until screen "night_map"
        click "翻开最后一册工作簿"
        advance until screen "night_map"
        click "和陆弥看一张暂时失效的船票"
        advance until screen "choice"
        click "那就现在问。等你安顿下来，我能去看看你的工作室吗？"
        advance until screen "night_map"
        click "问许澄，空白后面是什么"
        advance until screen "choice"
        click "不用替所有人决定。今晚，你愿意怎么听、怎么让别人听？"
        advance until screen "night_map"
        click "带备用保险去配电房"
        advance until screen "night_map"
        assert eval logic.has("BroadcastReady")
        assert eval not logic.has("Seen", scene="cheng_pause")
        click "留在电台，听一会儿雨"
        advance until screen "night_map"
        click "留在电台，听一会儿雨"
        advance until screen "night_map"
        click "留在电台，听一会儿雨"
        advance until screen "night_map"
        click "留在电台，听一会儿雨"
        advance until screen "choice"
        assert eval night.tick() == 12
        click "按大家同意的方式，做完最后一场广播。"
        advance until screen "ending_card"
        assert eval night.ending() == "harbor"

    testcase ending_quiet:
        click "留在电台，听一会儿雨"
        advance until screen "night_map"
        click "留在电台，听一会儿雨"
        advance until screen "night_map"
        click "留在电台，听一会儿雨"
        advance until screen "night_map"
        click "留在电台，听一会儿雨"
        advance until screen "night_map"
        click "留在电台，听一会儿雨"
        advance until screen "night_map"
        click "留在电台，听一会儿雨"
        advance until screen "night_map"
        click "留在电台，听一会儿雨"
        advance until screen "night_map"
        click "留在电台，听一会儿雨"
        advance until screen "night_map"
        click "留在电台，听一会儿雨"
        advance until screen "night_map"
        click "留在电台，听一会儿雨"
        advance until screen "night_map"
        click "留在电台，听一会儿雨"
        advance until screen "night_map"
        click "留在电台，听一会儿雨"
        advance until screen "choice"
        assert eval night.tick() == 12
        assert eval not night.can("last_broadcast", "broadcast")
        click "不勉强补完节目。一起收好东西，道一声晚安。"
        advance until screen "ending_card"
        assert eval night.ending() == "quiet"

    testcase adverse_choices_and_private_ending:
        click "听陆弥说起录音上的名字"
        advance until screen "choice"
        click "时间不多，我先拿回去，之后再补登记。"
        advance until screen "choice"
        click "我只是想帮忙。大家不应该把事情想得这么坏。"
        advance until screen "night_map"
        click "陪许澄听那段突然结束的录音"
        advance until screen "choice"
        click "先把这句播出去，也许有人知道后半段。"
        advance until screen "night_map"
        click "看看林遥压在工具箱下的车票"
        advance until screen "choice"
        click "可你走了，这里以后坏了东西找谁？"
        advance until screen "night_map"
        click "翻开最后一册工作簿"
        advance until screen "night_map"
        click "向林遥借一枚备用保险"
        advance until screen "choice"
        click "电台都要关了，就别计较一枚保险了。"
        advance until screen "night_map"
        click "和陆弥看一张暂时失效的船票"
        advance until screen "choice"
        click "船都停了，也许是在提醒你别走。"
        advance until screen "night_map"
        click "问许澄，空白后面是什么"
        advance until screen "choice"
        click "如果不想听，我们就把它封好，今晚不再问。"
        advance until screen "night_map"
        assert eval night.tick() == 7
        assert eval night.choice("power", "off")
        click "烧一壶不必赶着喝完的水"
        advance until screen "choice"
        click "给自己倒一杯，允许这一刻不派上用场。"
        advance until screen "night_map"
        click "留在电台，听一会儿雨"
        advance until screen "night_map"
        click "留在电台，听一会儿雨"
        advance until screen "night_map"
        click "留在电台，听一会儿雨"
        advance until screen "night_map"
        click "留在电台，听一会儿雨"
        advance until screen "choice"
        assert eval logic.has("Item", item="master_tape", holder="station")
        assert eval not logic.has("Consent", person="cheng", topic="recording")
        assert eval not night.can("last_broadcast", "broadcast")
        click "把声音留给愿意坐在这里的人。"
        advance until screen "ending_card"
        assert eval night.ending() == "quiet"

    testcase early_archive_and_friendship:
        click "听陆弥说起录音上的名字"
        advance until screen "choice"
        click "我想借走，先让许澄决定怎么处理。登记写在哪里？"
        advance until screen "night_map"
        assert eval logic.has("Here", person="mi", place="archive")
        click "把母带带回电台"
        advance until screen "night_map"
        click "陪许澄听那段突然结束的录音"
        advance until screen "choice"
        click "先别按播放。你想听见后面是什么吗？"
        advance until screen "night_map"
        click "翻开最后一册工作簿"
        advance until screen "night_map"
        assert eval not logic.has("Knows", clue="mi_leaving")
        click "问许澄，空白后面是什么"
        advance until screen "choice"
        click "不用替所有人决定。今晚，你愿意怎么听、怎么让别人听？"
        advance until screen "night_map"
        click "把明天的问题留给许澄回答"
        advance until screen "choice"
        click "我想继续见你。但现在还不能把这句话说成恋爱。"
        advance until screen "night_map"
        assert eval not logic.has("MutualFuture")
        click "留在电台，听一会儿雨"
        advance until screen "night_map"
        click "烧一壶不必赶着喝完的水"
        advance until screen "choice"
        click "给自己倒一杯，允许这一刻不派上用场。"
        advance until screen "night_map"
        assert eval night.tick() == 8
        assert eval night.choice("power", "off")
        click "留在电台，听一会儿雨"
        advance until screen "night_map"
        click "留在电台，听一会儿雨"
        advance until screen "night_map"
        click "留在电台，听一会儿雨"
        advance until screen "night_map"
        click "留在电台，听一会儿雨"
        advance until screen "choice"
        click "把声音留给愿意坐在这里的人。"
        advance until screen "ending_card"
        assert eval night.ending() == "quiet"

    testcase save_load_and_branch:
        click "看看林遥压在工具箱下的车票"
        advance until screen "choice"
        click "票都买好了。等到了，先告诉我那边食堂怎么样。"
        advance until screen "night_map"
        run Function(renpy.save, "tidelight-test")
        click "向林遥借一枚备用保险"
        advance until screen "choice"
        click "借给我好吗？今晚我来换，你只在旁边看着。"
        advance until screen "night_map"
        assert eval night.tick() == 2
        assert eval logic.has("Item", item="spare_fuse", holder="station")
        run Function(renpy.load, "tidelight-test")
        advance until screen "night_map"
        assert eval night.tick() == 1
        click "翻开手记"
        assert screen "diary"
        assert eval len(renpy.get_screen("diary").scope["clues"]) > 0
        run Function(renpy.screenshot, "/tmp/tidelight-diary.png")
        click "合上手记"
        assert eval logic.has("Item", item="spare_fuse", holder="yao")
        assert eval not logic.has("Seen", scene="yao_fuse")
        click "听陆弥说起录音上的名字"
        advance until screen "choice"
        click "我想借走，先让许澄决定怎么处理。登记写在哪里？"
        advance until screen "night_map"
        assert eval night.tick() == 2
        assert eval not logic.has("Consent", person="yao", topic="help")

    testcase rollback_and_diary:
        assert eval len(renpy.get_screen("night_map").scope["opportunities"]) == 4
        run Function(renpy.screenshot, "/tmp/tidelight-map.png")
        click "看看林遥压在工具箱下的车票"
        advance until screen "choice"
        run Function(renpy.screenshot, "/tmp/tidelight-choice.png")
        click "票都买好了。等到了，先告诉我那边食堂怎么样。"
        advance until screen "night_map"
        assert eval night.tick() == 1
        run Rollback() until eval not logic.has("Seen", scene="yao_ticket") timeout 10
        assert eval night.tick() == 0
        assert eval not logic.has("Knows", clue="yao_leaving")
        run MainMenu(confirm=False)
        click "开始这一夜"
        advance until screen "night_map"
        click "翻开手记"
        assert screen "diary"
        click "合上手记"
        keysym "K_F8"
        if eval config.developer:
            assert screen "weave_inspector"
            run Function(renpy.screenshot, "/tmp/tidelight-inspector.png")
            keysym "K_F8"
            assert not screen "weave_inspector"
        else:
            assert not screen "weave_inspector"
