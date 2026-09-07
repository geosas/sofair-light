var thing_resp
//var url_service = "https://frost.geosas.fr/station_meteo_hydro_agro/v1.0"
//var url_service = "https://frost.geosas.fr/stationmeteo/v1.0"
//var url_service = 'https://frost.geosas.fr/beauregard/v1.0'
var date_start
var date_end
var dernierSelectionne = null;

le_container.classList.remove('container')

document.getElementById('thingID').addEventListener('change', function () {
    thingID = this.value; // Récupère l'URL entrée par l'utilisateur
    metadataForm.classList.remove("is-hidden")
})

const average = array => array.reduce((a, b) => a + b) / array.length;

function get_sta(url_service, parametre) {
    console.log('start get sta data dl')
    console.log(url_service)
    data_info = fetch(url_service + "/" + parametre)
        .then((response) => response.json())
        .then((data) => {
            return data['value']
        });
    return data_info
}

function parseDate(date) {
    date = new Date(date);

    // fournir le jour de la semaine avec une date longue
    options = {
        weekday: "long",
        year: "numeric",
        month: "long",
        day: "numeric",
        hour: "numeric",
        minute: "numeric",
        second: "numeric"
    };
    return date.toLocaleDateString("fr-FR", options)
}


document.getElementById("metadataForm").addEventListener("submit", function (event) {
    event.preventDefault();  // Empêche le rechargement de la page

    message_pgb.classList.remove("is-hidden");

    // Récupérer les valeurs du formulaire
    let formData = new FormData();

    formData.append("conductiviteInit", document.getElementById("conductiviteInit").value);
    formData.append("masseSel", document.getElementById("masseSel").value);
    formData.append("intervalle", document.getElementById("intervalle").value);
    formData.append("input_data1", document.getElementById("input_data1").files[0]);
    formData.append("input_data2", document.getElementById("input_data2").files[0]);
    formData.append("input_data3", document.getElementById("input_data3").files[0]);


    // Envoyer les données en JSON via un POST
    fetch("/tarage/calculate-debit", {
        method: "POST",
        headers: {
            'X-CSRF-TOKEN': (document.cookie.match(/csrf_access_token=([^;]+)/) || [])[1]
        },
        body: formData,
        credentials: 'same-origin',
    })
        .then(response => response.json())
        .then(data => {
            const messageDiv = document.getElementById("message");
            messageDiv.classList.remove("is-hidden");
            messageDiv.classList.add("is-success");
            messageDiv.textContent = "Calcul effectué avec succès !";
            message_pgb.classList.add("is-hidden");
            console.log(data);
            let texte = `Débit moyen : ${Math.round(average(data['debit']) * 1000) / 1000} L/s, Incertitude : ${data['incertitude']}%`;
            debit_calcul.textContent = texte;

            texte = "Débit "
            data.debit.forEach((valeur, index) => {
                texte += `${index + 1} : ${valeur} L/s`;
                if (index < data.debit.length - 1) texte += ", ";
            });
            debit_src.textContent = texte;
            /////////////
            const labels = data.dataArray.components;
            const rawValues = data.dataArray.values;
            const dataSerie = rawValues.map(row => {
                return [
                    new Date(row[0]),
                    parseFloat(row[1]),
                    parseFloat(row[2]),
                    parseFloat(row[3])
                ];
            });

            // Crée le Dygraph
            new Dygraph(
                document.getElementById('graphdiv'),
                dataSerie,
                {
                    labels: labels,
                    title: 'Conductivité mesurée (mS)',
                    legend: 'always',
                    drawPoints: true,
                    labelsDiv: document.getElementById('customLegend'),
                    labelsKMB: true

                }
            );
        })
    btn_validation.classList.remove("is-hidden");


})
    .catch(error => {
        const messageDiv = document.getElementById("message");
        messageDiv.classList.remove("is-hidden");
        messageDiv.classList.add("is-danger");
        messageDiv.textContent = "Erreur lors du calcul.";
        message_pgb.classList.add("is-hidden");

    });
