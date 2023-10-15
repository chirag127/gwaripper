// emebd local audio file
$(document).ready(function() {
    $('.entry-container-title').click(function(event) {
        $(event.currentTarget).parents(".entry-container").find(".entry-expand").toggle();
        event.preventDefault();
    });
    $('.set-fav-btn').click(function(event) {
        let ribbon = $(event.currentTarget).parents(".entry-container").find(".ribbon");
        let fav_btn = $(event.currentTarget);
        let fav_icon = fav_btn.find(".fa-heart");
        let entry_id = $(event.currentTarget).data("entryId");
        let fav_intbool = $(event.currentTarget).data("favIntbool");
        if(fav_intbool == 1) {
            ribbon.removeClass("gwa-hidden");
            ribbon.addClass("gwa-visible");

            fav_icon.removeClass("fas");
            fav_icon.addClass("far");
            fav_btn.data("favIntbool", 0);
            fav_btn.title = "Un-favorite audio!";
        } else {
            ribbon.removeClass("gwa-visible");
            ribbon.addClass("gwa-hidden");

            fav_icon.removeClass("far");
            fav_icon.addClass("fas");
            fav_btn.data("favIntbool", 1);
            fav_btn.title = "Favorite audio!";
        }
        event.preventDefault();

        $.ajax({
            data : {
                "entryId": entry_id,
                "favIntbool": fav_intbool
            },
            type : 'POST',
            url : rootUrl + '/entry/set-favorite',
            // let jquery know that flask is returning json data
            // (data in func below)
            dataType: "json"
        }).done(function(data) {
            if (data.error) {
                console.log(data.error);
            } else {
                // set to opposite
                fav_btn.data("favIntbool", 1 - fav_intbool);
            }
        });
    });
});